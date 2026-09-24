#!/usr/bin/env python
"""SLAM3R ply driver.

Run the SLAM3R pipeline (github.com/pku-vcl-3dv/slam3r) on a video and export
one merged .ply point cloud. Frames are extracted with ffmpeg, the offline
reconstruction runs through SLAM3R's own recon.py, and the *_recon.ply result
is copied to the requested output path. All code and model files are fetched
once into a gitignored workspace dir under scripts/. Inference runs on one
NVIDIA GPU (RTX 5070 Ti by default).

Notes from the repo:
- The model regresses point maps without intrinsics, so no calibration is
  needed for a self-captured video.
- The saved cloud is not metric: 1 unit is the mean camera-to-scene distance
  of the initial window.
- xformers and the compiled RoPE kernels are optional upstream; the pure
  PyTorch fallbacks run them, so neither is installed here.

Needs: uv on PATH, git (fallback: GitHub tarball download), ffmpeg on PATH,
one NVIDIA GPU.
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

REPO_URL = "https://github.com/pku-vcl-3dv/slam3r.git"
TARBALL_URL = "https://codeload.github.com/pku-vcl-3dv/slam3r/tar.gz/refs/heads/main"
# cu130 matches the CUDA 13 toolkit here; sm_120 needs cu128 or newer wheels
TORCH_INDEX = "https://download.pytorch.org/whl/cu130"
TORCH_SPEC = ["torch==2.9.1+cu130", "torchvision==0.24.1+cu130"]
# Minimal runtime deps: opencv + trimesh feed the frame loader and the ply
# exporter; huggingface-hub[torch] handles the checkpoint auto-download.
DEPS_SPEC = [
    "opencv-python",
    "trimesh",
    "matplotlib",
    "tqdm",
    "scipy",
    "einops",
    "huggingface-hub[torch]>=0.22",
]
DEPS_IMPORT_CHECK = (
    "import cv2, trimesh, matplotlib, tqdm, scipy, einops, huggingface_hub"
)
RESULT_PREFIX = "SLAM3R_PLY_RESULT "

DEFAULT_I2P_MODEL = "siyan824/slam3r_i2p"
DEFAULT_L2W_MODEL = "siyan824/slam3r_l2w"

MODEL_FETCH_SNIPPET = """
import sys
sys.path.insert(0, r"{slam3r_root}")
from slam3r.models import Image2PointsModel, Local2WorldModel
Image2PointsModel.from_pretrained('{i2p_model}')
Local2WorldModel.from_pretrained('{l2w_model}')
print("slam3r checkpoints present")
"""


def _log(msg: str) -> None:
    typer.echo(f"[slam3r-ply] {msg}")


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
    """Clone SLAM3R once. Fall back to a tarball download when git is absent."""
    target = workspace / "slam3r"
    if (target / "slam3r" / "__init__.py").is_file():
        _log("SLAM3R code present, skip clone")
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
    archive = tmp / "slam3r.tar.gz"
    with urllib.request.urlopen(TARBALL_URL, timeout=180) as resp:
        archive.write_bytes(resp.read())
    with tarfile.open(archive, "r:gz") as tf:
        tf.extractall(tmp)  # noqa: S202 - fixed public URL
    root = next(
        p for p in tmp.iterdir()
        if p.is_dir() and p.name.lower().startswith("slam3r")
    )
    shutil.move(str(root), str(target))
    shutil.rmtree(tmp)
    if not (target / "slam3r" / "__init__.py").is_file():
        raise RuntimeError("SLAM3R code download did not produce slam3r/__init__.py")


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
        [uv_bin, "pip", "install", "--python", venv_py, *TORCH_SPEC,
         "--index-url", TORCH_INDEX]
    )
    _stream_run(check)  # raise if the sm_120 build is still missing


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


def _model_fetch(workspace: Path, i2p_model: str, l2w_model: str) -> None:
    """Prefetch the two HF checkpoints into the workspace HF cache."""
    venv_py = _venv_python(workspace)
    snippet = MODEL_FETCH_SNIPPET.format(
        slam3r_root=str(workspace / "slam3r"), i2p_model=i2p_model, l2w_model=l2w_model
    )
    env = os.environ.copy()
    env["HF_HOME"] = str(workspace / "hf-home")
    try:
        _stream_run([venv_py, "-c", snippet], env=env)
        _log(f"models {i2p_model}, {l2w_model} present")
    except RuntimeError:
        # retry once without the network mask in case the hub cache is partial
        _stream_run([venv_py, "-c", snippet], env=env)


def _extract_frames(video: Path, frames_dir: Path, fps: int) -> int:
    """Extract numbered frames with ffmpeg; reuse the dir when it is complete."""
    if frames_dir.is_dir() and len(list(frames_dir.glob("*.jpg"))) > 0:
        frames = sorted(frames_dir.glob("*.jpg"))
        _log(f"frame cache present: {len(frames)} frames in {frames_dir}")
        return len(frames)
    frames_dir.mkdir(parents=True, exist_ok=True)
    # the log stays outside the frames dir: SLAM3R sorts the dir listing and
    # chokes on a file whose name does not end in a number
    status = frames_dir.parent / f"{frames_dir.name}.extraction.log"
    with open(status, "w") as log:
        proc = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(video), "-vf", f"fps={fps}",
                "-q:v", "2", str(frames_dir / "%05d.jpg"),
            ],
            stdout=log, stderr=log,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg frame extraction failed, see {status} "
            f"(ffmpeg needs HEVC support for this video)"
        )
    frames = sorted(frames_dir.glob("*.jpg"))
    if not frames:
        raise RuntimeError(f"ffmpeg produced no frames in {frames_dir}")
    _log(f"extracted {len(frames)} frames at {fps} fps -> {frames_dir}")
    return len(frames)


def _ensure_workspace(workspace: Path, i2p_model: str, l2w_model: str, uv_bin: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    _fetch_code(workspace)
    _venv_create(workspace, uv_bin)
    _torch_install(workspace, uv_bin)
    _deps_install(workspace, uv_bin)
    _model_fetch(workspace, i2p_model, l2w_model)


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


def _find_recon_ply(results_dir: Path) -> Path:
    """The run writes <scene_id>_recon.ply into the test dir."""
    candidates = sorted(results_dir.glob("*_recon.ply"), key=lambda p: p.stat().st_size)
    if not candidates:
        raise RuntimeError(f"no *_recon.ply produced under {results_dir}")
    return candidates[-1]  # keep the largest result file


@app.command()
def ply(
    video_path: Path = typer.Argument(..., help="Path to an .mp4 (or other ffmpeg-readable) video."),
    workspace: Path = typer.Option(
        Path(__file__).resolve().parent / ".slam3r-workspace",
        help="Workspace dir for code, venv, frame cache and model files.",
    ),
    output: Path = typer.Option(None, help="Output .ply path. Default: <video dir>/<stem>_slam3r.ply."),
    i2p_model: str = typer.Option(DEFAULT_I2P_MODEL, help="Hugging Face id of the Image-to-Points model."),
    l2w_model: str = typer.Option(DEFAULT_L2W_MODEL, help="Hugging Face id of the Local-to-World model."),
    fps: int = typer.Option(10, help="Frame extraction fps. 10 suits a handheld walkthrough."),
    keyframe_stride: int = typer.Option(
        3, help="Stride between consecutive I2P/L2W windows; -1 enables auto adaptation."
    ),
    win_r: int = typer.Option(5, help="Radius of the I2P input window."),
    initial_winsize: int = typer.Option(5, help="Frames in the scene initialization window."),
    conf_thres_i2p: float = typer.Option(1.5, help="Confidence threshold for the I2P model."),
    conf_thres_l2w: float = typer.Option(12, help="Confidence threshold when saving the final cloud."),
    num_scene_frame: int = typer.Option(10, help="Scene frames retrieved from the buffer per keyframe."),
    max_num_register: int = typer.Option(10, help="Maximal frames registered in one go."),
    update_buffer_intv: int = typer.Option(1, help="Buffer refresh interval (x keyframe stride)."),
    buffer_size: int = typer.Option(100, help="Maximal buffer size; -1 means unlimited."),
    buffer_strategy: str = typer.Option(
        "reservoir", help="reservoir suits a single room; fifo suits larger scenes."
    ),
    num_points_save: int = typer.Option(1_000_000, help="Final cloud subsample cap."),
    norm_input: bool = typer.Option(False, "--norm-input", help="Normalize the input point maps for L2W."),
    save_preds: bool = typer.Option(
        False, "--save-preds", help="Keep the per-frame .npy predictions next to the .ply."
    ),
    re_extract: bool = typer.Option(
        False, "--re-extract", help="Re-extract the frame cache even when it exists."
    ),
    seed: int = typer.Option(42, help="Random seed."),
    gpu_match: str = typer.Option("5070 Ti", help="GPU name substring to pick."),
    gpu_index: int = typer.Option(-1, help="Explicit GPU index; -1 uses --gpu-match."),
) -> None:
    """Run SLAM3R on VIDEO_PATH and export one merged .ply point cloud."""
    t0 = time.perf_counter()
    if not video_path.is_file():
        raise typer.BadParameter(f"video not found: {video_path}")
    if buffer_strategy not in ("reservoir", "fifo"):
        raise typer.BadParameter("--buffer-strategy must be reservoir or fifo")
    if not shutil.which("ffmpeg"):
        raise typer.BadParameter("ffmpeg not found on PATH; needed for frame extraction")
    uv_bin = shutil.which("uv")
    if not uv_bin:
        raise typer.BadParameter("uv not found on PATH; install https://docs.astral.sh/uv/")
    out_path = output if output else video_path.parent / f"{video_path.stem}_slam3r.ply"
    frames_dir = workspace / "frames" / f"{video_path.stem}_fps{fps}"

    _ensure_workspace(workspace, i2p_model, l2w_model, uv_bin)
    gpu_index_used, gpu_name = _pick_gpu(gpu_match, gpu_index)
    _log(f"GPU {gpu_index_used}: {gpu_name}")

    if re_extract and frames_dir.is_dir():
        shutil.rmtree(frames_dir)
    num_frames = _extract_frames(video_path.resolve(), frames_dir, fps)

    test_name = f"{video_path.stem}_fps{fps}"
    cmd = [
        _venv_python(workspace), str(workspace / "slam3r" / "recon.py"),
        "--test_name", test_name,
        "--img_dir", str(frames_dir.resolve()),
        "--gpu_id", "0",
        "--keyframe_stride", str(keyframe_stride),
        "--win_r", str(win_r),
        "--initial_winsize", str(initial_winsize),
        "--conf_thres_i2p", str(conf_thres_i2p),
        "--conf_thres_l2w", str(conf_thres_l2w),
        "--num_scene_frame", str(num_scene_frame),
        "--max_num_register", str(max_num_register),
        "--update_buffer_intv", str(update_buffer_intv),
        "--buffer_size", str(buffer_size),
        "--buffer_strategy", buffer_strategy,
        "--num_points_save", str(num_points_save),
        "--seed", str(seed),
    ] + (["--norm_input"] if norm_input else []) \
      + (["--save_preds"] if save_preds else [])
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index_used)
    env["HF_HOME"] = str(workspace / "hf-home")
    env["PYTHONUNBUFFERED"] = "1"
    # results land relative to this cwd, inside the gitignored workspace
    slam3r_root = workspace / "slam3r"

    t_run = time.perf_counter()
    _stream_run(cmd, env=env, cwd=slam3r_root)
    elapsed = time.perf_counter() - t_run

    src_ply = _find_recon_ply(slam3r_root / "results" / test_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_ply, out_path)

    result = {
        "ply": str(out_path.resolve()),
        "source_ply": str(src_ply.resolve()),
        "frames_dir": str(frames_dir.resolve()),
        "num_frames": num_frames,
        "fps": fps,
        "points_file_size_bytes": out_path.stat().st_size,
        "seconds": elapsed,
        "total_seconds": time.perf_counter() - t0,
        "device": gpu_name,
        "gpu_index": gpu_index_used,
    }
    _log(f"GPU: {gpu_name}")
    _log(f"wall time: {elapsed:.1f} s")
    _log(f"ply: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f} MiB)")
    print(RESULT_PREFIX + json.dumps(result), flush=True)


def main() -> None:
    try:
        app()
    except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
        typer.echo(f"[slam3r-ply] ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    main()
