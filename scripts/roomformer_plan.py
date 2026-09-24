#!/usr/bin/env python
"""RoomFormer plan driver.

Run the RoomFormer pipeline (github.com/ywyue/RoomFormer, CVPR 2023) offline
on a scaled, vertically aligned .ply point cloud and export a 2D vector floor
plan (SVG + JSON). RoomFormer consumes a top-down density map projected from
the point cloud, so the runner cleans outliers, projects the cloud along the
vertical axis, and decodes room polygons. All code and model files are fetched
once into a workspace dir under scripts/. Inference runs on one NVIDIA GPU
(RTX 5070 Ti by default).

Needs: uv on PATH, git (fallback: GitHub tarball download), one NVIDIA GPU.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)

REPO_URL = "https://github.com/ywyue/RoomFormer.git"
TARBALL_URL = "https://codeload.github.com/ywyue/RoomFormer/tar.gz/refs/heads/main"
# polybox Nextcloud share from the repo README; WebDAV download, no auth
CKPT_URL = "https://polybox.ethz.ch/public.php/dav/files/vlBo66X0NTrcsTC/?accept=zip"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
# cu118 wheels have no sm_120 kernels, so the torch 1.9 pins are replaced
TORCH_SPEC = ["torch==2.9.1+cu128", "torchvision==0.24.1+cu128"]
# fvcore, omegaconf, yacs and friends feed the detectron2 imports inside
# models/losses.py; open3d reads the .ply; scipy feeds the matcher import
DEPS_SPEC = [
    "numpy==1.26.4",
    "scipy>=1.15",
    "shapely>=2.0",
    "pillow",
    "open3d==0.18.0",
    "fvcore",
    "omegaconf>=2.3",
    "yacs",
    "tabulate",
    "termcolor",
    "cloudpickle",
    "matplotlib",
    "portalocker",
    "pycocotools",
]
DEPS_IMPORT_CHECK = (
    "import numpy, scipy, shapely, PIL, open3d, torch, fvcore, omegaconf, "
    "yacs, tabulate, termcolor, cloudpickle, matplotlib, portalocker, pycocotools"
)
RESULT_PREFIX = "ROOMFORMER_PLAN_RESULT "

VARIANTS = {
    "stru3d": {"checkpoint": "roomformer_stru3d.pth", "num_queries": 800, "num_polys": 20, "semantic_classes": -1},
    "tight": {"checkpoint": "roomformer_stru3d_tight.pth", "num_queries": 800, "num_polys": 20, "semantic_classes": -1},
    "semantic": {"checkpoint": "roomformer_stru3d_semantic_rich.pth", "num_queries": 2800, "num_polys": 70, "semantic_classes": 19},
}
# Structured3D room type ids; 16 is door and 17 is window
# (data_preprocess/stru3d/stru3d_utils.py type2id)
ROOM_TYPES = [
    "living room", "kitchen", "bedroom", "bathroom", "balcony", "corridor",
    "dining room", "study", "studio", "store room", "garden", "laundry room",
    "office", "basement", "garage", "undefined",
]

# Compat patches for torch 2.9 + torchvision 0.24 on RTX 5070 Ti (sm_120).
# The multi-scale deformable attention compiled extension (python 3.8 only)
# is replaced with the pure PyTorch core, and torchvision's removed
# `pretrained=` kwarg is dropped (all weights come from the checkpoint).
PATCH_OPS_IMPORT_OLD = "import MultiScaleDeformableAttention as MSDA\n"
PATCH_OPS_IMPORT_NEW = (
    "try:\n"
    "    import MultiScaleDeformableAttention as MSDA\n"
    "except ImportError:\n"
    "    MSDA = None  # RF_PLAN_COMPAT: run the pure PyTorch core when the ext is missing\n"
)
PATCH_OPS_APPLY_OLD = (
    "    @staticmethod\n"
    "    def forward(ctx, value, value_spatial_shapes, value_level_start_index, sampling_locations, attention_weights, im2col_step):\n"
    "        ctx.im2col_step = im2col_step\n"
)
PATCH_OPS_APPLY_NEW = (
    "    @staticmethod\n"
    "    def forward(ctx, value, value_spatial_shapes, value_level_start_index, sampling_locations, attention_weights, im2col_step):\n"
    "        if MSDA is None:\n"
    "            # RF_PLAN_COMPAT: compiled extension missing, run the pure PyTorch core\n"
    "            return ms_deform_attn_core_pytorch(value, value_spatial_shapes, sampling_locations, attention_weights)\n"
    "        ctx.im2col_step = im2col_step\n"
)
PATCH_BACKBONE_OLD = (
    "            replace_stride_with_dilation=[False, False, dilation],\n"
    "            pretrained=True, norm_layer=norm_layer)\n"
)
PATCH_BACKBONE_NEW = (
    "            replace_stride_with_dilation=[False, False, dilation],\n"
    "            weights=None, norm_layer=norm_layer)  # RF_PLAN_COMPAT: weights come from the checkpoint\n"
)
PATCHES = []

IMPORT_CHECK_SNIPPET = """
import sys, types
sys.path.insert(0, r"{codero}")
try:
    import native_rasterizer
except ModuleNotFoundError:
    stub = types.ModuleType("native_rasterizer")

    def _missing(*_a, **_k):
        raise RuntimeError("diff_ras CUDA extension is not compiled; polygon decode needs no runtime rasterizer")

    stub.forward_rasterize = _missing
    stub.backward_rasterize = _missing
    sys.modules["native_rasterizer"] = stub
from models import build_model
print("roomformer imports ok")
"""


def _log(msg: str) -> None:
    typer.echo(f"[roomformer-plan] {msg}")


def _stream_run(cmd: list, env: dict | None = None, cwd: Path | None = None) -> list[str]:
    """Run a command, stream its output live, keep it for the error report."""
    _log("$ " + " ".join(str(c) for c in cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(cwd) if cwd else None,
    )
    lines: list[str] = []
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            lines.append(line)
            typer.echo(line, nl=False)
        proc.stdout.close()  # type: ignore[union-attr]
    except KeyboardInterrupt:  # pragma: no cover - user abort
        proc.kill()
        raise
    finally:
        proc.wait()
    if proc.returncode != 0:
        tail = "".join(lines[-30:])
        raise RuntimeError(
            f"command failed with code {proc.returncode}: "
            f"{' '.join(str(c) for c in cmd)}\n--- last output ---\n{tail}"
        )
    return lines


def _venv_python(workspace: Path) -> Path:
    return workspace / ".venv" / "bin" / "python"


def _fetch_code(workspace: Path) -> None:
    """Clone RoomFormer once. Fall back to a tarball download when git fails."""
    target = workspace / "RoomFormer"
    if (target / "models" / "__init__.py").is_file():
        _log("RoomFormer code present, skip clone")
        return
    if target.exists():
        shutil.rmtree(target)
    try:
        _stream_run(["git", "clone", "--depth", "1", REPO_URL, str(target)])
        return
    except (RuntimeError, FileNotFoundError) as exc:
        _log(f"git clone failed ({exc.__class__.__name__}), fall back to tarball")
    tmp = workspace / "_code_download"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    archive = tmp / "roomformer.tar.gz"
    with urllib.request.urlopen(TARBALL_URL, timeout=180) as resp:
        archive.write_bytes(resp.read())
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmp)  # noqa: S202 - fixed public URL
    root = next(p for p in tmp.iterdir() if p.is_dir() and p.name.startswith("RoomFormer"))
    shutil.move(str(root), str(target))
    shutil.rmtree(tmp)
    if not (target / "models" / "__init__.py").is_file():
        raise RuntimeError("RoomFormer code download did not produce models/__init__.py")


def _apply_patch(path: Path, old: str, new: str) -> None:
    """Patch one idempotent replacement into a repo file."""
    if not path.is_file():
        raise RuntimeError(f"missing file for patch: {path}")
    text = path.read_text()
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"patch target not found in {path}; upstream file changed")
    path.write_text(text.replace(old, new))


def _patch_repo(workspace: Path) -> None:
    """Make the repo run under torch 2.9 without compiled CUDA extensions."""
    ops_func = workspace / "RoomFormer" / "models" / "ops" / "functions" / "ms_deform_attn_func.py"
    _apply_patch(ops_func, PATCH_OPS_IMPORT_OLD, PATCH_OPS_IMPORT_NEW)
    _apply_patch(ops_func, PATCH_OPS_APPLY_OLD, PATCH_OPS_APPLY_NEW)
    backbone = workspace / "RoomFormer" / "models" / "backbone.py"
    _apply_patch(backbone, PATCH_BACKBONE_OLD, PATCH_BACKBONE_NEW)
    _log("torch compat patches applied (MSDA pytorch core, checkpoint weights)")


def _venv_create(workspace: Path, uv_bin: str) -> None:
    venv_py = _venv_python(workspace)
    if venv_py.is_file():
        _log("venv present, skip creation")
        return
    venv_dir = workspace / ".venv"
    if venv_dir.exists():
        shutil.rmtree(venv_dir)  # clean a partial venv
    _stream_run([uv_bin, "venv", "--python", "3.11", str(venv_dir)])


def _torch_install(workspace: Path, uv_bin: str) -> None:
    venv_py = _venv_python(workspace)
    check = [venv_py, "-c", "import torch; assert torch.cuda.is_available()"]
    try:
        _stream_run(check)
        _log("torch with CUDA present, skip install")
        return
    except RuntimeError:
        pass
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py, *TORCH_SPEC, "--index-url", TORCH_INDEX]
    )
    _stream_run(check)  # raise if the Blackwell build is still missing


def _deps_install(workspace: Path, uv_bin: str) -> None:
    venv_py = _venv_python(workspace)
    check = [venv_py, "-c", DEPS_IMPORT_CHECK]
    try:
        _stream_run(check)
        _log("all deps present, skip install")
        return
    except RuntimeError:
        pass
    _stream_run([uv_bin, "pip", "install", "--python", venv_py, *DEPS_SPEC])
    _stream_run(check)


def _repo_import_check(workspace: Path) -> None:
    """Smoke test the model build path inside the venv before real inference."""
    venv_py = _venv_python(workspace)
    codero = workspace / "RoomFormer"
    text = IMPORT_CHECK_SNIPPET.replace("{codero}", str(codero))
    _stream_run([venv_py, "-c", text])


def _checkpoint_fetch(workspace: Path, variant: str) -> None:
    """Download the RoomFormer checkpoints zip once and extract the .pth files."""
    if shutil.which("curl") is None:
        raise RuntimeError("curl not found on PATH; needed for the checkpoint download")
    ckpt_dir = workspace / "checkpoints"
    zip_path = workspace / "checkpoints.zip"
    needed = [VARIANTS[variant]["checkpoint"]]

    def present(name: str) -> bool:
        p = Path(ckpt_dir) / name
        return p.is_file() and p.stat().st_size > 1e8

    if all(present(n) for n in needed):
        _log("checkpoints present, skip download")
        if zip_path.is_file():
            zip_path.unlink()  # free the 1.6 GiB archive copy
    else:
        _log(f"downloading checkpoints (~1.9 GiB) from {CKPT_URL}")
        try:
            _stream_run(["curl", "-fL", "-C", "-", "--progress-bar", CKPT_URL, "-o", str(zip_path)])
        except RuntimeError as res_err:
            if not zip_path.exists():
                raise
            # a leftover complete zip answers 416 to resume; start over
            _log(f"resume failed ({res_err.__class__.__name__}), restart the download from zero")
            zip_path.unlink(missing_ok=True)
            _stream_run(["curl", "-fL", "--progress-bar", CKPT_URL, "-o", str(zip_path)])
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        venv_py = _venv_python(workspace)
        try:
            # members carry the checkpoints/ prefix, extract into the workspace root
            _stream_run(
                [
                    venv_py,
                    "-c",
                    "import sys, zipfile; z = zipfile.ZipFile(sys.argv[1]);"
                    " z.extractall(sys.argv[2]); print('extracted', len(z.namelist()), 'entries')",
                    str(zip_path),
                    str(workspace),
                ]
            )
            for name in needed:
                if not present(name):
                    raise RuntimeError(f"checkpoint extraction incomplete: {name} not found")
        except Exception:
            zip_path.unlink(missing_ok=True)  # keep reruns working
            raise
        zip_path.unlink()  # free the 1.9 GiB archive copy
    _log("checkpoints present: " + ", ".join(needed))


def _ensure_workspace(workspace: Path, uv_bin: str, variant: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    # keep the matplotlib cache inside the workspace (HOME config may be read-only)
    mpl_dir = workspace / "mpl-cache"
    mpl_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))
    _fetch_code(workspace)
    _venv_create(workspace, uv_bin)
    _torch_install(workspace, uv_bin)
    _deps_install(workspace, uv_bin)
    _patch_repo(workspace)
    _repo_import_check(workspace)
    _checkpoint_fetch(workspace, variant)


def _pick_gpu(match: str, index: int) -> tuple[int, str]:
    """Pick one GPU index from nvidia-smi names. On this box the 5070 Ti wins."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        raise RuntimeError("nvidia-smi not found; need an NVIDIA GPU")
    try:
        out = subprocess.run(
            [smi, "--query-gpu=index,name", "--format=csv,noheader"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError(f"nvidia-smi query failed: {exc}") from exc
    rows = []
    for line in out.splitlines():
        idx, _, name = line.partition(",")
        rows.append((idx.strip(), name.strip()))
    if not rows:
        raise RuntimeError("nvidia-smi listed no GPUs")
    if index >= 0:
        if index >= len(rows):
            raise RuntimeError(f"--gpu-index {index} out of range ({len(rows)} GPUs)")
        return int(index), rows[index][1]
    for idx, name in rows:
        if match.lower() in name.lower():
            return int(idx), name
    _log(f"no GPU name contains {match!r}, falling back to index 0: {rows[0][1]}")
    return 0, rows[0][1]


@app.command()
def plan(
    ply_path: Path = typer.Argument(..., help="Path to a scaled, vertically aligned .ply point cloud."),
    workspace: Path = typer.Option(
        Path(__file__).resolve().parent / ".roomformer-workspace",
        help="Workspace dir for code, venv and checkpoint files.",
    ),
    variant: str = typer.Option(
        "stru3d", help="Model variant: stru3d, tight (tighter rooms) or semantic (room types, doors, windows)."
    ),
    output_dir: Path = typer.Option(None, help="Output dir. Default: <ply dir>/<ply stem>_roomformer_plan/."),
    sor_neighbors: int = typer.Option(30, help="Statistical outlier removal neighborhood size."),
    sor_std: float = typer.Option(2.0, help="Statistical outlier removal std ratio."),
    voxel_size: float = typer.Option(
        -1.0, help="Voxel pre-pass in meters to equalize the density histogram: "
                   "-1 auto, 0 disables, >0 explicit."
    ),
    z_min: float | None = typer.Option(None, help="Optional z floor for a height band filter (meters)."),
    z_max: float | None = typer.Option(None, help="Optional z ceiling for a height band filter (meters)."),
    min_area_px: float = typer.Option(
        100.0, help="Minimum room polygon area in density pixels, same filter as eval.py."
    ),
    corner_threshold: float = typer.Option(
        0.5, help="Corner validity threshold, same as eval.py. Lower to 0.2-0.3 for sparse clouds."
    ),
    density_gamma: float = typer.Option(
        1.0, help="Gamma exponent on the density map for fine control after tuning."
    ),
    bright_fraction: float = typer.Option(
        0.05, help="Initial share of pixels brighter than 128 as a value from 0 to 1 "
        "(0.05 = 5 percent). The search halves it while the model finds more rooms than "
        "--target-rooms, and raises it when it finds none. 0 disables the search and "
        "uses the official max normalization."
    ),
    target_rooms: int = typer.Option(
        1, help="Room count the iterative brightness search stops at."
    ),
    density_only: bool = typer.Option(
        False, "--density-only",
        help="Export the density image at the requested share and stop, "
        "without the model or inference.",
    ),
    gpu_match: str = typer.Option("5070 Ti", help="GPU name substring to pick."),
    gpu_index: int = typer.Option(-1, help="Explicit GPU index; -1 uses --gpu-match."),
) -> None:
    """Run the RoomFormer pipeline on PLY_PATH and export 2D vector plans."""
    t0 = time.perf_counter()
    if not ply_path.is_file():
        raise typer.BadParameter(f"point cloud not found: {ply_path}")
    if variant not in VARIANTS:
        raise typer.BadParameter(f"unsupported --variant {variant}; pick one of {', '.join(VARIANTS)}")
    if min(sor_neighbors, sor_std, min_area_px) <= 0:
        raise typer.BadParameter("--sor-neighbors, --sor-std and --min-area-px must stay positive")
    if not 0 <= corner_threshold <= 1:
        raise typer.BadParameter("--corner-threshold must stay in [0, 1]")
    if density_gamma <= 0:
        raise typer.BadParameter("--density-gamma must stay positive")
    if not 0 <= bright_fraction <= 1:
        raise typer.BadParameter("--bright-fraction must stay in [0, 1] (0 disables the search)")
    if target_rooms < 1:
        raise typer.BadParameter("--target-rooms must stay at least 1")
    uv_bin = shutil.which("uv")
    if not uv_bin:
        raise typer.BadParameter("uv not found on PATH; install https://docs.astral.sh/uv/")
    out_dir = output_dir if output_dir else ply_path.parent / f"{ply_path.stem}_roomformer_plan"
    out_dir.mkdir(parents=True, exist_ok=True)

    _ensure_workspace(workspace, uv_bin, variant)
    gpu_index_used, gpu_name = _pick_gpu(gpu_match, gpu_index)
    _log(f"GPU {gpu_index_used}: {gpu_name}")

    cfg = VARIANTS[variant]
    scripts_dir = Path(__file__).resolve().parent
    cmd = [
        _venv_python(workspace),
        scripts_dir / "roomformer_plan_runner.py",
        "--input", str(ply_path.resolve()),
        "--output-dir", str(out_dir),
        "--codero", str(workspace / "RoomFormer"),
        "--checkpoint", str(workspace / "checkpoints" / cfg["checkpoint"]),
        "--variant", variant,
        "--num-queries", str(cfg["num_queries"]),
        "--num-polys", str(cfg["num_polys"]),
        "--semantic-classes", str(cfg["semantic_classes"]),
        "--sor-neighbors", str(sor_neighbors),
        "--sor-std", str(sor_std),
        "--voxel-size", str(voxel_size),
        "--min-area-px", str(min_area_px),
        "--corner-threshold", str(corner_threshold),
        "--density-gamma", str(density_gamma),
        "--bright-fraction", str(bright_fraction),
        "--target-rooms", str(target_rooms),
        "--gpu-index-used", str(gpu_index_used),
    ] + (["--density-only"] if density_only else [])
    if z_min is not None:
        cmd += ["--z-min", str(z_min)]
    if z_max is not None:
        cmd += ["--z-max", str(z_max)]

    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index_used)
    env["PYTHONUNBUFFERED"] = "1"

    t_run = time.perf_counter()
    lines = _stream_run(cmd, env=env)
    elapsed = time.perf_counter() - t_run

    result = None
    for line in reversed(lines):
        if line.startswith(RESULT_PREFIX):
            result = json.loads(line[len(RESULT_PREFIX):])
            break
    if result is None:
        raise RuntimeError("runner finished but printed no result line")

    _log(f"GPU: {result.get('device', gpu_name)}")
    _log(f"wall time: {elapsed:.1f} s")
    _log("outputs:")
    for key in ("density_png", "svg", "json"):
        path = result.get(key)
        if path and Path(path).is_file():
            _log(f"  {path} ({Path(path).stat().st_size / 1024:.1f} KiB)")
    stats = {k: result.get(k) for k in ("rooms", "doors", "windows")}
    _log(f"elements: {json.dumps(stats)}")
    _log(f"total: {time.perf_counter() - t0:.1f} s")


def main() -> None:
    try:
        app()
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        typer.echo(f"[roomformer-plan] ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    main()
