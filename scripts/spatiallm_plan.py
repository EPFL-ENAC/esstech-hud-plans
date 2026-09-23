#!/usr/bin/env python
"""SpatialLM plan driver.

Run the SpatialLM pipeline (github.com/manycore-research/SpatialLM offline) on a
scaled, vertically aligned .ply point cloud and export a 2D vector floor plan
(SVG + JSON). All code and model files are fetched once into a workspace dir
under scripts/. Inference runs on one NVIDIA GPU (RTX 5070 Ti by default).

Needs: uv on PATH, git (fallback: GitHub tarball download), one NVIDIA GPU.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)

REPO_URL = "https://github.com/manycore-research/SpatialLM.git"
TARBALL_URL = "https://codeload.github.com/manycore-research/SpatialLM/tar.gz/refs/heads/main"
TORCH_INDEX = "https://download.pytorch.org/whl/cu128"
TORCH_SCATTER_FIND_LINKS = "https://data.pyg.org/whl/torch-2.9.0+cu128.html"
# cu124 has no sm_120 kernels, so the poetry pins must be replaced with these.
TORCH_SPEC = ["torch==2.9.1+cu128", "torchvision==0.24.1+cu128"]
# transformers 4.46.1 + tokenizers <0.20.4 + numpy 1.26.4: python 3.11 set,
# verified against SpatialLM1.1 inference.
DEPS_SPEC = [
    "transformers==4.46.1",
    "tokenizers>=0.20.0,<0.20.4",
    "safetensors>=0.4.5,<0.5",
    "numpy==1.26.4",
    "scipy>=1.15",
    "open3d==0.18.0",
    "tqdm",
    "addict",
    "timm",
    "huggingface_hub>=0.25",
    "pandas",
    "poetry-core",
    "setuptools",
    "wheel",
]
DEPS_IMPORT_CHECK = (
    "import transformers, tokenizers, safetensors, numpy, scipy, open3d, "
    "tqdm, addict, timm, huggingface_hub, spconv, cumm, torch_scatter, pandas"
)
RESULT_PREFIX = "SPATIALLM_PLAN_RESULT "

DEFAULT_MODEL = "manycore-research/SpatialLM1.1-Qwen-0.5B"

# Sonata encoder uses flash-attn by default. FA2 has no Blackwell build, so the
# default is patched to the SDPA fallback (maintainer-endorsed via patch).


def _log(msg: str) -> None:
    typer.echo(f"[spatiallm-plan] {msg}")


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


def _model_dir(workspace: Path, model_id: str) -> Path:
    safe = model_id.replace("/", "_")
    return workspace / "models" / safe


def _fetch_code(workspace: Path) -> None:
    """Clone SpatialLM once. Fall back to a tarball download when git is absent."""
    target = workspace / "SpatialLM"
    if (target / "spatiallm" / "__init__.py").is_file():
        _log("SpatialLM code present, skip clone")
        return
    if target.exists():
        shutil.rmtree(target)
    try:
        _stream_run(
            ["git", "clone", "--depth", "1", REPO_URL, str(target)]
        )
        return
    except (RuntimeError, FileNotFoundError) as exc:
        _log(f"git clone failed ({exc.__class__.__name__}), fall back to tarball")
    tmp = workspace / "_code_download"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    archive = tmp / "spatiallm.tar.gz"
    with urllib.request.urlopen(TARBALL_URL, timeout=180) as resp:
        archive.write_bytes(resp.read())
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmp)  # noqa: S202 - fixed public URL
    root = next(p for p in tmp.iterdir() if p.is_dir() and p.name.startswith("SpatialLM"))
    shutil.move(str(root), str(target))
    shutil.rmtree(tmp)
    if not (target / "spatiallm" / "__init__.py").is_file():
        raise RuntimeError("SpatialLM code download did not produce spatiallm/__init__.py")


def _patch_repo_metadata(workspace: Path) -> None:
    """Drop local version segments (+cu124) from Poetry dependency specs.

    poetry-core emits `torch (>=2.4.1+cu124,<3.0.0)` into package metadata;
    uv rejects local segments in comparators (PEP 440) even with --no-deps.
    The torch stack is installed separately with sm_120 cu128 wheels.
    """
    path = workspace / "SpatialLM" / "pyproject.toml"
    if not path.is_file():
        return
    text = path.read_text()
    patched = re.sub(r'(\{ version = "[^"]*?)\+cu\d+', r"\1", text)
    if patched != text:
        path.write_text(patched)
        _log("sanitized +cu124 local segments in SpatialLM pyproject.toml")
    else:
        _log("SpatialLM pyproject.toml already sanitized")


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
    except RuntimeError as first:
        _log(f"deps check failed: {first}")
    _stream_run([uv_bin, "pip", "install", "--python", venv_py, *DEPS_SPEC])
    _stream_run([uv_bin, "pip", "install", "--python", venv_py, "spconv-cu120"])
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py, "torch-scatter", "--find-links", TORCH_SCATTER_FIND_LINKS]
    )
    try:
        _stream_run(check)
        return
    except RuntimeError as sparse_err:
        _log(f"sparse deps still broken, trying cu126 fallback: {sparse_err}")
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py, "--reinstall-package", "cumm", "--reinstall-package", "spconv", "cumm==0.7.3", "spconv-cu126"]
    )
    _stream_run(check)


def _spatiallm_install(workspace: Path, uv_bin: str) -> None:
    venv_py = _venv_python(workspace)
    check = [venv_py, "-c", "from spatiallm import Layout"]
    try:
        _stream_run(check)
        _log("spatiallm package present, skip install")
        return
    except RuntimeError:
        pass
    # --no-deps keeps the poetry torch pin out; deps come from the steps above.
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py, "--no-deps", "--no-build-isolation", "-e", str(workspace / "SpatialLM")]
    )
    _stream_run(check)


def _patch_flash(workspace: Path) -> None:
    """Point Sonata encoder flash calls at the SDPA fallback (no FA2 on Blackwell)."""
    patched = []
    for path in sorted((workspace / "SpatialLM").glob("spatiallm/**/*.py")):
        text = path.read_text()
        if "enable_flash=True" in text:
            path.write_text(text.replace("enable_flash=True", "enable_flash=False"))
            patched.append(path.name)
    _log(f"flash-attn fallback patch applied to: {', '.join(patched) if patched else 'none (already patched)'}")


def _patch_streamer_timeout(workspace: Path) -> None:
    """Give the generation streamer 600 s; stock 20 s can lapse before the
    first token on a cold CUDA context (encoder + prefill warmup)."""
    path = workspace / "SpatialLM" / "inference.py"
    if not path.is_file():
        return
    text = path.read_text()
    if "timeout=20.0" in text:
        path.write_text(text.replace("timeout=20.0", "timeout=600.0"))
        _log("raised streamer timeout in inference.py to 600 s")
    else:
        _log("streamer timeout already raised")


def _model_fetch(workspace: Path, model_id: str, uv_bin: str) -> Path:
    model_dir = _model_dir(workspace, model_id)
    has_weights = (model_dir / "model.safetensors").is_file() or list(
        model_dir.glob("model-00001-of-*.safetensors")
    )
    if has_weights and (model_dir / "config.json").is_file():
        _log(f"model {model_id} present, skip download")
        return model_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["HF_HOME"] = str(workspace / "hf-home")  # hub cache stays in the workspace
    _stream_run(
        [
            _venv_python(workspace),
            "-m",
            "huggingface_hub.commands.huggingface_cli",
            "download",
            model_id,
            "--local-dir",
            str(model_dir),
        ],
        env=env,
    )
    if not (model_dir / "config.json").is_file():
        raise RuntimeError(f"model download incomplete: no config.json in {model_dir}")
    return model_dir


def _ensure_workspace(workspace: Path, model_id: str, uv_bin: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    _fetch_code(workspace)
    _patch_repo_metadata(workspace)
    _venv_create(workspace, uv_bin)
    _torch_install(workspace, uv_bin)
    _deps_install(workspace, uv_bin)
    _spatiallm_install(workspace, uv_bin)
    _patch_flash(workspace)
    _patch_streamer_timeout(workspace)
    _model_fetch(workspace, model_id, uv_bin)


def _pick_gpu(match: str, index: int) -> tuple[int, str]:
    """Pick one GPU index from nvidia-smi names. On this box the 5070 Ti wins."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        raise RuntimeError("nvidia-smi not found; need an NVIDIA GPU")
    out = subprocess.run(
        [smi, "--query-gpu=index,name", "--format=csv,noheader"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    rows = []
    for line in out.splitlines():
        idx, _, name = line.partition(",")
        rows.append((idx.strip(), name.strip()))
    if index >= 0:
        if index >= len(rows):
            raise RuntimeError(f"--gpu-index {index} out of range ({len(rows)} GPUs)")
        return index, rows[index][1]
    for idx, name in rows:
        if match.lower() in name.lower():
            return int(idx), name
    _log(f"no GPU name contains {match!r}, falling back to index 0: {rows[0][1]}")
    return 0, rows[0][1]


@app.command()
def plan(
    ply_path: Path = typer.Argument(..., help="Path to a scaled, vertically aligned .ply point cloud."),
    workspace: Path = typer.Option(
        Path(__file__).resolve().parent / ".spatiallm-workspace",
        help="Workspace dir for code, venv and model files.",
    ),
    model: str = typer.Option(DEFAULT_MODEL, help="Hugging Face model repo id (SpatialLM1.x)."),
    detect_type: str = typer.Option("arch", help="Inference targets: arch, object or all."),
    output_dir: Path = typer.Option(None, help="Output dir. Default: <ply dir>/<ply stem>_plan/."),
    seed: int = typer.Option(-1, help="Random seed; -1 means unset."),
    temperature: float = typer.Option(0.6, help="Sampling temperature."),
    top_p: float = typer.Option(0.95, help="Top-p sampling."),
    top_k: int = typer.Option(10, help="Top-k sampling."),
    num_beams: int = typer.Option(1, help="Beam size."),
    dtype: str = typer.Option("bfloat16", help="Model weights dtype: float16, bfloat16 or float32."),
    no_cleanup: bool = typer.Option(False, "--no-cleanup", help="Skip point cloud outlier cleanup."),
    default_wall_thickness: float = typer.Option(0.1, help="Draw width for walls emitted with ~0 thickness."),
    gpu_match: str = typer.Option("5070 Ti", help="GPU name substring to pick."),
    gpu_index: int = typer.Option(-1, help="Explicit GPU index; -1 uses --gpu-match."),
) -> None:
    """Run the SpatialLM pipeline on PLY_PATH and export 2D vector plans."""
    t0 = time.perf_counter()
    if not ply_path.is_file():
        raise typer.BadParameter(f"point cloud not found: {ply_path}")
    if dtype not in ("float16", "bfloat16", "float32"):
        raise typer.BadParameter(f"unsupported dtype {dtype}")
    if detect_type not in ("arch", "object", "all"):
        raise typer.BadParameter(f"unsupported --detect-type {detect_type}")
    uv_bin = shutil.which("uv")
    if not uv_bin:
        raise typer.BadParameter("uv not found on PATH; install https://docs.astral.sh/uv/")
    out_dir = output_dir if output_dir else ply_path.parent / f"{ply_path.stem}_plan"
    out_dir.mkdir(parents=True, exist_ok=True)

    _ensure_workspace(workspace, model, uv_bin)
    gpu_index_used, gpu_name = _pick_gpu(gpu_match, gpu_index)
    _log(f"GPU {gpu_index_used}: {gpu_name}")

    scripts_dir = Path(__file__).resolve().parent
    cmd = [
        _venv_python(workspace),
        scripts_dir / "spatiallm_plan_runner.py",
        "--input", str(ply_path.resolve()),
        "--output-dir", str(out_dir),
        "--workspace", str(workspace),
        "--model-dir", str(_model_dir(workspace, model)),
        "--model-id", model,
        "--detect-type", detect_type,
        "--seed", str(seed),
        "--temperature", str(temperature),
        "--top-p", str(top_p),
        "--top-k", str(top_k),
        "--num-beams", str(num_beams),
        "--dtype", dtype,
        "--default-wall-thickness", str(default_wall_thickness),
    ]
    if no_cleanup:
        cmd.append("--no-cleanup")
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index_used)
    env["HF_HOME"] = str(workspace / "hf-home")
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
    for key in ("layout_txt", "svg", "json"):
        path = result.get(key)
        if path and Path(path).is_file():
            _log(f"  {path} ({Path(path).stat().st_size / 1024:.1f} KiB)")
    stats = {k: result.get(k) for k in ("walls", "doors", "windows", "furniture")}
    _log(f"entities: {json.dumps(stats)}")
    _log(f"total: {time.perf_counter() - t0:.1f} s")


def main() -> None:
    try:
        app()
    except RuntimeError as exc:
        typer.echo(f"[spatiallm-plan] ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    main()
