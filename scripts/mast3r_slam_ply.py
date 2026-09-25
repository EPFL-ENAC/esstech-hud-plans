#!/usr/bin/env python
"""MASt3R-SLAM ply driver.

Run the MASt3R-SLAM pipeline (github.com/rmurai0610/MASt3R-SLAM) on a video
and export one merged .ply point cloud. The repo's own main.py handles the
mp4 input, adaptive keyframes and reconstruction, and writes the final cloud
via save_reconstruction; this driver copies that cloud to the requested
output path. All code, patches, checkpoints and model files are fetched once
into a gitignored workspace dir under scripts/. Inference runs on one NVIDIA
GPU (RTX 5070 Ti by default).

Notes from the repo:
- Without --calib, MASt3R point maps give the scale, so an uncalibrated video
  needs calibration in config/base.yaml (use_calib False).
- The merged .ply accumulates all keyframes in the world frame.
- The CUDA backend (mast3r_slam_backends) and the lietorch fork must compile;
  a system nvcc >= 12.8 is a hard prerequisite. The gn_kernels/matching
  patches mirror upstream PR #86 for sm_90/sm_120 and torch >= 2.6.
- torchcodec is skipped; the built-in cv2 video decoder fallback runs the mp4.

Needs: uv on PATH, git (with submodule support), ffmpeg on PATH, nvcc >= 12.8
(CUDA_HOME or /opt/cuda or /usr/local/cuda*), one NVIDIA GPU.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)

REPO_URL = "https://github.com/rmurai0610/MASt3R-SLAM.git"
# cu130 matches the CUDA 13 toolkit here; sm_120 needs cu128 or newer wheels
TORCH_INDEX = "https://download.pytorch.org/whl/cu130"
TORCH_SPEC = ["torch==2.9.1+cu130", "torchvision==0.24.1+cu130"]
# setuptools 70.0.0 + numpy feed the --no-build-isolation package builds below
BASE_DEPS_SPEC = ["setuptools==70.0.0", "wheel", "numpy==1.26.4"]
# validated Blackwell/cu128+ fork of lietorch (upstream unpatched for new torch)
LIETORCH_URL = "https://github.com/nicogorlo/lietorch"
MAST3R_CKPT_URL = (
    "https://download.europe.naverlabs.com/ComputerVision/MASt3R/"
    "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth"
)
MAST3R_CKPT_NAME = "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric.pth"
RETRIEVAL_CKPT_URL = (
    "https://download.europe.naverlabs.com/ComputerVision/MASt3R/"
    "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth"
)
RETRIEVAL_CKPT_NAME = (
    "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_trainingfree.pth"
)
# Codebook needed by the trainingfree retrieval (loop closure helper); without
# it the helper process dies at startup and retrieval loop closure is inactive
CODEBOOK_URL = (
    "https://download.europe.naverlabs.com/ComputerVision/MASt3R/"
    "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_codebook.pkl"
)
CODEBOOK_NAME = (
    "MASt3R_ViTLarge_BaseDecoder_512_catmlpdpt_metric_retrieval_codebook.pkl"
)
RESULT_PREFIX = "MAST3RSLAM_PLY_RESULT "

# Blackwell + torch >= 2.9 compat patches, mirroring upstream PR #86 (unmerged
# at the time of writing) plus the checkpoint loading default change
# (weights_only=True is the torch >= 2.6 default). The sm_90/sm_120 gencode is
# added when the system nvcc supports it.
PATCH_GENCODE_OLD = (
    '        "-gencode=arch=compute_86,code=sm_86",\n'
    "    ]\n"
    "    ext_modules = [\n"
)
PATCH_GENCODE_NEW = (
    '        "-gencode=arch=compute_86,code=sm_86",\n'
    "    ]\n"
    "    cuda_version = torch.version.cuda or ''\n"
    "    cuda_major_minor = tuple(int(p) for p in cuda_version.split('.')[:2])\n"
    "    # MAST3R_SLAM_PATCH: sm_90/sm_120 nvcc flags when the toolkit supports them\n"
    "    if cuda_major_minor >= (11, 8):\n"
    '        extra_compile_args["nvcc"].append("-gencode=arch=compute_90,code=sm_90")\n'
    "    if cuda_major_minor >= (12, 8):\n"
    '        extra_compile_args["nvcc"].append("-gencode=arch=compute_120,code=sm_120")\n'
    "    # MAST3R_SLAM_PATCH: CUDA >= 13 removes Maxwell/Pascal/Volta; drop\n"
    "    # those hardcoded gencodes so nvcc does not stop early\n"
    "    if cuda_major_minor >= (13, 0):\n"
    "        for _old_arch in (\"-gencode=arch=compute_60,code=sm_60\",\n"
    "                          \"-gencode=arch=compute_61,code=sm_61\",\n"
    "                          \"-gencode=arch=compute_70,code=sm_70\"):\n"
    "            if _old_arch in extra_compile_args[\"nvcc\"]:\n"
    "                extra_compile_args[\"nvcc\"].remove(_old_arch)\n"
    "    ext_modules = [\n"
)
# block written by an earlier driver version (before the CUDA 13 removal)
PATCH_GENCODE_CHECK_OLD = (
    '        "-gencode=arch=compute_86,code=sm_86",\n'
    "    ]\n"
    "    cuda_version = torch.version.cuda or ''\n"
    "    cuda_major_minor = tuple(int(p) for p in cuda_version.split('.')[:2])\n"
    "    # MAST3R_SLAM_PATCH: sm_90/sm_120 nvcc flags when the toolkit supports them\n"
    "    if cuda_major_minor >= (11, 8):\n"
    '        extra_compile_args["nvcc"].append("-gencode=arch=compute_90,code=sm_90")\n'
    "    if cuda_major_minor >= (12, 8):\n"
    '        extra_compile_args["nvcc"].append("-gencode=arch=compute_120,code=sm_120")\n'
    "    ext_modules = [\n"
)
PATCH_GN_LINALG_OLD = (
    "delta_norm = torch::linalg::linalg_norm(dx, std::optional<c10::Scalar>(), {}, false, {});"
)
PATCH_GN_LINALG_NEW = (
    "delta_norm = at::linalg_norm(dx, c10::nullopt, {}, false, c10::nullopt);"
)
PATCH_MATCHING_OLD = (
    'AT_DISPATCH_FLOATING_TYPES_AND_HALF(D11.type(), "refine_matches_kernel", ([&] {'
)
PATCH_MATCHING_NEW = (
    'AT_DISPATCH_FLOATING_TYPES_AND_HALF(D11.scalar_type(), "refine_matches_kernel", ([&] {'
)
PATCH_CUROPE_OLD = (
    'AT_DISPATCH_FLOATING_TYPES_AND_HALF(tokens.type(), "rope_2d_cuda", ([&] {'
)
PATCH_CUROPE_NEW = (
    'AT_DISPATCH_FLOATING_TYPES_AND_HALF(tokens.scalar_type(), "rope_2d_cuda", ([&] {'
)
PATCH_LIETORCH_OLD = '"lietorch @ git+https://github.com/princeton-vl/lietorch.git",'
# the driver installs lietorch itself (with controlled gencodes), so the
# declarative line stays out of uv resolution to avoid a URL rebuild
PATCH_LIETORCH_NEW = (
    "# lietorch comes from a Blackwell-ready fork and is installed by this\n"
    "    # driver with compatible gencodes; commented out here so uv does not\n"
    "    # rebuild it from a URL\n"
)

# Controlled replacement for the lietorch fork setup.py: the upstream file
# pins Maxwell/Pascal/Volta gencodes that CUDA >= 13 nvcc rejects
LIETORCH_SETUP = """from setuptools import setup
from torch.utils.cpp_extension import BuildExtension, CUDAExtension

import os.path as osp

ROOT = osp.dirname(osp.abspath(__file__))

# LIETORCH_PLY_PATCH: the upstream setup.py pins Maxwell/Pascal/Volta gencodes
# that CUDA >= 13 nvcc rejects (nvcc fatal: unsupported gpu architecture).
# No explicit gencodes here, so the torch build picks arch flags from
# TORCH_CUDA_ARCH_LIST (if set) or from the supported archs of its own build.

setup(
    name='lietorch',
    version='0.2',
    description='Lie Groups for PyTorch',
    author='teedrz',
    packages=['lietorch'],
    ext_modules=[
        CUDAExtension('lietorch_backends',
            include_dirs=[
                osp.join(ROOT, 'lietorch/include'),
                osp.join(ROOT, 'eigen')],
            sources=[
                'lietorch/src/lietorch.cpp',
                'lietorch/src/lietorch_gpu.cu',
                'lietorch/src/lietorch_cpu.cpp'],
            extra_compile_args={
                'cxx': ['-O2'],
                'nvcc': ['-O2'],
            }),

        CUDAExtension('lietorch_extras',
            sources=[
                'lietorch/extras/altcorr_kernel.cu',
                'lietorch/extras/corr_index_kernel.cu',
                'lietorch/extras/se3_builder.cu',
                'lietorch/extras/se3_inplace_builder.cu',
                'lietorch/extras/se3_solver.cu',
                'lietorch/extras/extras.cpp',
            ],
            extra_compile_args={
                'cxx': ['-O2'],
                'nvcc': ['-O2'],
            }),
    ],
    cmdclass={ 'build_ext': BuildExtension }
)
"""


def _log(msg: str) -> None:
    typer.echo(f"[mast3r-slam-ply] {msg}")


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
        tail = "".join(lines[-40:])
        raise RuntimeError(
            f"command failed with code {proc.returncode}: "
            f"{' '.join(str(c) for c in cmd)}\n--- last output ---\n{tail}"
        )
    return lines


def _venv_python(workspace: Path) -> Path:
    return workspace / ".venv" / "bin" / "python"


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
    """Make the code build and run under torch 2.9 on sm_120 (PR #86 mirror)."""
    repo = workspace / "MASt3R-SLAM"
    setup_py = repo / "setup.py"
    if PATCH_GENCODE_NEW not in setup_py.read_text():
        try:
            _apply_patch(setup_py, PATCH_GENCODE_OLD, PATCH_GENCODE_NEW)
        except RuntimeError:
            # upgrade clones patched by an earlier driver version
            _apply_patch(setup_py, PATCH_GENCODE_CHECK_OLD, PATCH_GENCODE_NEW)
    # three identical linalg_norm call sites in gn_kernels.cu
    _apply_patch(repo / "mast3r_slam" / "backend" / "src" / "gn_kernels.cu",
                 PATCH_GN_LINALG_OLD, PATCH_GN_LINALG_NEW)
    _apply_patch(repo / "mast3r_slam" / "backend" / "src" / "matching_kernels.cu",
                 PATCH_MATCHING_OLD, PATCH_MATCHING_NEW)
    # torch >= 2.6 loads checkpoints with weights_only=True by default; the
    # MASt3R files embed argparse args, so the load needs weights_only=False
    _apply_patch(repo / "thirdparty" / "mast3r" / "mast3r" / "model.py",
                 "ckpt = torch.load(model_path, map_location='cpu')",
                 "ckpt = torch.load(model_path, map_location='cpu', weights_only=False)")
    _apply_patch(repo / "thirdparty" / "mast3r" / "mast3r" / "retrieval" / "processor.py",
                 "ckpt = torch.load(modelname, 'cpu')",
                 "ckpt = torch.load(modelname, 'cpu', weights_only=False)")
    # curope builds as a dependency of thirdparty/mast3r
    _apply_patch(repo / "thirdparty" / "mast3r" / "dust3r" / "croco" / "models" / "curope" / "kernels.cu",
                 PATCH_CUROPE_OLD, PATCH_CUROPE_NEW)
    try:
        _apply_patch(repo / "pyproject.toml", PATCH_LIETORCH_OLD, PATCH_LIETORCH_NEW)
    except RuntimeError:
        # clones patched by an earlier driver version carry the fork URL line;
        # comment it out the same way
        _apply_patch(
            repo / "pyproject.toml",
            f'"lietorch @ git+{LIETORCH_URL}.git",',
            PATCH_LIETORCH_NEW,
        )
    _log("torch 2.9 + sm_120 + lietorch fork patches applied")


def _fetch_code(workspace: Path) -> None:
    """Clone MASt3R-SLAM once with submodules (eigen + pyimgui).

    The two submodules are required at build time (thirdparty/eigen include
    dir feeds the backend build; pyimgui is a source dependency of in3d),
    so git is a hard requirement and no tarball fallback exists.
    """
    target = workspace / "MASt3R-SLAM"
    present = (
        (target / "mast3r_slam" / "__init__.py").is_file()
        and (target / "thirdparty" / "mast3r" / "setup.py").is_file()
        and (target / "thirdparty" / "in3d" / "setup.py").is_file()
        and (target / "thirdparty" / "eigen" / ".git").exists()
        and (target / "thirdparty" / "in3d" / "thirdparty" / "pyimgui" / "setup.py").is_file()
    )
    if present:
        _log("MASt3R-SLAM code present, skip clone")
        return
    if target.exists():
        shutil.rmtree(target)
    if shutil.which("git") is None:
        raise RuntimeError("git not found on PATH; MASt3R-SLAM needs it for submodules")
    # the global git config pins the git-lfs filter (filter.lfs.required=true)
    # while git-lfs itself is absent; neutralize the filter so LFS-tracked
    # files (pyimgui doc pngs, media gifs) check out as plain pointer files
    git_lfs_off = [
        "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=",
        "-c", "filter.lfs.required=false",
    ]
    _stream_run(["git", *git_lfs_off, "clone", "--depth", "1", REPO_URL, str(target)])
    env = os.environ.copy()
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    _stream_run(
        ["git", *git_lfs_off, "-C", str(target),
         "submodule", "update", "--init", "--recursive", "--depth", "1"],
        env=env,
    )
    if not (target / "thirdparty" / "eigen" / "Eigen" / "Core").is_file() and not (
        target / "thirdparty" / "eigen" / "Eigen" / "Core"
    ).exists():
        raise RuntimeError("eigen submodule did not populate thirdparty/eigen")


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


def _build_env(workspace: Path) -> dict:
    """Env for the CUDA builds: CUDA_HOME plus a gcc-15 host compiler.

    The system gcc (16.2.1) is too new for the torch 2.9 headers inside nvcc
    host passes (ATen/core/List_inl.h raises 'need typename' errors under
    gcc 16's -Wtemplate-body). gcc-15 sits next to it on this box and feeds
    both the nvcc host compiler (PATH shim with gcc-15 first) and the cxx
    compile steps (CC/CXX env).
    """
    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", str(workspace / "mpl-cache"))
    if "CUDA_HOME" not in env or not env["CUDA_HOME"]:
        for cand in ("/opt/cuda", "/usr/local/cuda", "/usr/local/cuda-13.0",
                     "/usr/local/cuda-12.8"):
            if Path(cand, "bin", "nvcc").is_file():
                env["CUDA_HOME"] = cand
                break
    cc_bin = shutil.which("gcc-15")
    cxx_bin = shutil.which("c++-15") or shutil.which("g++-15")
    if cc_bin and cxx_bin:
        env["CC"] = cc_bin
        env["CXX"] = cxx_bin
        env["CUDAHOSTCXX"] = cxx_bin
        # gcc >= 15 turns torch header template-body issues (ATen/core/List_inl.h
        # 'need typename') into fatal errors inside the nvcc host pass; downgrade
        # them back to warnings for every nvcc call
        env["NVCC_PREPEND_FLAGS"] = "-Xcompiler -Wno-template-body"
        # nvcc resolves the host compiler as plain `gcc` on PATH; a shim dir
        # with gcc-15 first keeps nvcc off the too-new system gcc
        shim = workspace / "ccbin-shim"
        shim.mkdir(parents=True, exist_ok=True)
        for name, target in (("gcc", cc_bin), ("c++", cxx_bin), ("g++", cxx_bin)):
            link = shim / name
            if not link.exists():
                link.symlink_to(target)
        env["PATH"] = str(shim) + os.pathsep + env["PATH"]
    return env


def _patch_torch_header(workspace: Path) -> None:
    """Patch ATen/core/List_inl.h for gcc >= 15 inside nvcc host passes.

    The inline header builds `static_cast<typename decltype(impl_->list)
    ::difference_type>`; gcc >= 15 refuses that dependent decltype inside a
    template body ('need typename' plus 'instantiating erroneous template').
    The list member is a std::vector, so its difference_type is std::ptrdiff_t.
    """
    targets = list(
        (workspace / ".venv").glob("lib/python3.*/site-packages/torch/include/ATen/core/List_inl.h")
    )
    if not targets:
        raise RuntimeError("torch include header List_inl.h not found in the workspace venv")
    for path in targets:
        text = path.read_text()
        fixed = ("return {impl_->list.begin() + "
                 "static_cast<std::ptrdiff_t>(pos)};  // LIETORCH_PLY_PATCH: gcc >= 15")
        if fixed in text:
            continue  # already patched
        broken = ("return {impl_->list.begin() + static_cast<std::ptrdiff_t>(pos)};"
                  "  # LIETORCH_PLY_PATCH: gcc>=15")
        if broken in text:
            # an earlier driver version wrote a '#' comment into C++; repair it
            text = text.replace(broken, fixed)
        else:
            old = ("return {impl_->list.begin() + static_cast<typename "
                   "decltype(impl_->list)::difference_type>(pos)};")
            if old not in text:
                raise RuntimeError(f"patch target not found in {path}; upstream file changed")
            text = text.replace(old, fixed)
        path.write_text(text)
    _log("torch List_inl.h gcc 15 patch applied")


def _base_deps_install(workspace: Path, uv_bin: str) -> None:
    """setuptools 70 + wheel + numpy 1.26.4, needed by the no-isolation builds."""
    venv_py = _venv_python(workspace)
    check = [venv_py, "-c", "import setuptools, numpy; import wheel"]
    try:
        _stream_run(check)
        _log("base deps present, skip install")
        return
    except RuntimeError:
        pass
    _stream_run([uv_bin, "pip", "install", "--python", venv_py, *BASE_DEPS_SPEC])
    _stream_run(check)


def _lietorch_install(workspace: Path, uv_bin: str) -> None:
    """Build the validated lietorch fork against the venv torch (needs nvcc).

    The fork source is cloned locally and its setup.py is replaced with a
    controlled one without hardcoded gencodes; upstream pins Maxwell/Pascal/
    Volta gencodes that CUDA >= 13 nvcc rejects.
    """
    venv_py = _venv_python(workspace)
    check = [venv_py, "-c", "import lietorch"]
    try:
        _stream_run(check)
        _log("lietorch present, skip install")
        return
    except RuntimeError:
        pass
    lietorch_dir = workspace / "lietorch"
    if not (lietorch_dir / "setup.py").is_file():
        if lietorch_dir.exists():
            shutil.rmtree(lietorch_dir)  # clean a partial clone
        # the eigen submodule (include dir) must come along; the doc image
        # is lfs-tracked, so the lfs filter stays neutralized
        _stream_run(
            [
                "git", "clone", "--depth", "1", "--shallow-submodules", "--recursive",
                "-c", "filter.lfs.smudge=", "-c", "filter.lfs.process=",
                "-c", "filter.lfs.required=false",
                LIETORCH_URL, str(lietorch_dir),
            ]
        )
    (lietorch_dir / "setup.py").write_text(LIETORCH_SETUP)
    env = _build_env(workspace)
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py, "--no-build-isolation",
         "-e", str(lietorch_dir)],
        env=env,
    )
    _stream_run(check)


def _mast3r_install(workspace: Path, uv_bin: str) -> None:
    """thirdparty/mast3r: deps plus the croco curope CUDA extension."""
    venv_py = _venv_python(workspace)
    # dust3r only resolves after mast3r.utils.path_to_dust3r inserts its path;
    # torch first loads libc10.so so the compiled extension imports resolve
    check = [venv_py, "-c",
             "import torch, mast3r, mast3r.utils.path_to_dust3r, dust3r, curope"]
    try:
        _stream_run(check)
        _log("mast3r present, skip install")
        return
    except RuntimeError:
        pass
    env = _build_env(workspace)
    # --no-build-isolation keeps the file-URI curope build inside the venv so
    # that its setup.py sees torch (the build would fail in an isolated env)
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py, "--no-build-isolation",
         "-e", str(workspace / "MASt3R-SLAM" / "thirdparty" / "mast3r")],
        env=env,
    )
    _stream_run(check)


def _in3d_install(workspace: Path, uv_bin: str) -> None:
    """thirdparty/in3d: pure python, but imgui builds from the pyimgui submodule."""
    venv_py = _venv_python(workspace)
    check = [venv_py, "-c", "import in3d, imgui, moderngl"]
    try:
        _stream_run(check)
        _log("in3d present, skip install")
        return
    except RuntimeError:
        pass
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py,
         "-e", str(workspace / "MASt3R-SLAM" / "thirdparty" / "in3d")],
        env=_build_env(workspace),
    )
    _stream_run(check)


def _slam_install(workspace: Path, uv_bin: str) -> None:
    """Main package: builds the mast3r_slam_backends CUDA extension."""
    venv_py = _venv_python(workspace)
    # torch first loads libc10.so so the compiled backend import resolves
    check = [venv_py, "-c", "import torch, mast3r_slam, mast3r_slam_backends"]
    try:
        _stream_run(check)
        _log("MASt3R-SLAM package present, skip install")
        return
    except RuntimeError:
        pass
    env = _build_env(workspace)
    _stream_run(
        [uv_bin, "pip", "install", "--python", venv_py, "--no-build-isolation", "-e",
         str(workspace / "MASt3R-SLAM")],
        env=env,
    )
    _stream_run(check)


def _checkpoint_fetch(workspace: Path) -> None:
    """Download the Naver checkpoints Main.py loads (2.6 GiB) plus the retrieval
    codebook (256 MiB, needed for the loop-closure helper)."""
    if shutil.which("curl") is None:
        raise RuntimeError("curl not found on PATH; needed for the checkpoint download")
    ckpt_dir = workspace / "MASt3R-SLAM" / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    targets = {
        MAST3R_CKPT_URL: (ckpt_dir / MAST3R_CKPT_NAME, 1e8),
        RETRIEVAL_CKPT_URL: (ckpt_dir / RETRIEVAL_CKPT_NAME, 1e6),
        CODEBOOK_URL: (ckpt_dir / CODEBOOK_NAME, 1e6),
    }
    for url, (dest, min_size) in targets.items():
        if dest.is_file() and dest.stat().st_size > min_size:
            _log(f"checkpoint present, skip download: {dest.name}")
            continue
        _log(f"downloading {dest.name}")
        _stream_run(["curl", "-fL", "-C", "-", "--progress-bar", url, "-o", str(dest)])
        if not dest.is_file() or dest.stat().st_size <= min_size:
            raise RuntimeError(f"checkpoint download incomplete: {dest}")


def _ensure_workspace(workspace: Path, uv_bin: str) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    _fetch_code(workspace)
    _patch_repo(workspace)
    _venv_create(workspace, uv_bin)
    _torch_install(workspace, uv_bin)
    _patch_torch_header(workspace)
    _base_deps_install(workspace, uv_bin)
    _lietorch_install(workspace, uv_bin)
    _mast3r_install(workspace, uv_bin)
    _in3d_install(workspace, uv_bin)
    _slam_install(workspace, uv_bin)
    _checkpoint_fetch(workspace)


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


def _find_saved_ply(logs_dir: Path, video_stem: str) -> Path:
    """main.py writes logs/<save-as>/<video stem>.ply plus a .txt trajectory."""
    candidates = sorted(logs_dir.glob(f"{video_stem}*.ply"))
    if not candidates:
        raise RuntimeError(f"no reconstruction .ply produced under {logs_dir}")
    return candidates[0]


@app.command()
def ply(
    video_path: Path = typer.Argument(..., help="Path to an .mp4 (or .avi/.MOV) video."),
    workspace: Path = typer.Option(
        Path(__file__).resolve().parent / ".mast3r-slam-workspace",
        help="Workspace dir for code, venv, patches and checkpoints.",
    ),
    output: Path = typer.Option(
        None, help="Output .ply path. Default: <video dir>/<stem>_mast3rslam.ply."
    ),
    config: str = typer.Option("config/base.yaml", help="Repo config file for the run."),
    calib: str = typer.Option(
        "", help="Optional intrinsics file for calibration; empty keeps uncalibrated mode."
    ),
    save_as: str = typer.Option(None, help="Run name under logs/; default <video stem>_mast3rslam."),
    gpu_match: str = typer.Option("5070 Ti", help="GPU name substring to pick."),
    gpu_index: int = typer.Option(-1, help="Explicit GPU index; -1 uses --gpu-match."),
) -> None:
    """Run MASt3R-SLAM on VIDEO_PATH and export one merged .ply point cloud."""
    t0 = time.perf_counter()
    if not video_path.is_file():
        raise typer.BadParameter(f"video not found: {video_path}")
    uv_bin = shutil.which("uv")
    if not uv_bin:
        raise typer.BadParameter("uv not found on PATH; install https://docs.astral.sh/uv/")
    repo = workspace / "MASt3R-SLAM"
    out_path = output if output else video_path.parent / f"{video_path.stem}_mast3rslam.ply"
    run_name = save_as if save_as else f"{video_path.stem}_mast3rslam"

    _ensure_workspace(workspace, uv_bin)
    gpu_index_used, gpu_name = _pick_gpu(gpu_match, gpu_index)
    _log(f"GPU {gpu_index_used}: {gpu_name}")

    cmd = [
        _venv_python(workspace), "main.py",
        "--dataset", str(video_path.resolve()),
        "--config", config,
        "--no-viz",
        "--save-as", run_name,
    ]
    if calib:
        cmd += ["--calib", calib]
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index_used)
    env["PYTHONUNBUFFERED"] = "1"

    t_run = time.perf_counter()
    _stream_run(cmd, env=env, cwd=repo)
    elapsed = time.perf_counter() - t_run

    src_ply = _find_saved_ply(repo / "logs" / run_name, video_path.stem)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_ply, out_path)

    result = {
        "ply": str(out_path.resolve()),
        "source_ply": str(src_ply.resolve()),
        "config": config,
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
        typer.echo(f"[mast3r-slam-ply] ERROR: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    main()
