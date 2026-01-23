import os
import shutil
import subprocess
import sys

os.environ["PYTHONUNBUFFERED"] = "1"  # Add at top of file

# Check if running inside a Docker container
IS_DOCKER = os.path.exists("/.dockerenv")

backend_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

commands_prefix = os.path.join(backend_root, "external", "bin")
ffmpeg_command = os.path.join(commands_prefix, "ffmpeg")

# Determine colmap command based on environment
colmap_path = os.path.join(commands_prefix, "colmap")
colmap_command = f"xvfb-run -a {colmap_path}" if IS_DOCKER else colmap_path

brush_command = os.path.join(commands_prefix, "brush")

output_prefix = os.path.join(backend_root, "data", "splats")


def generate_splats(job_name: str, input_video: str):
    print(f"Generating splats for job '{job_name}' from video '{input_video}'")

    root_path = os.path.join(output_prefix, job_name)
    dirs = prepare_dirs(root_path)
    print(f"Prepared directories: {dirs}", end="\n\n")

    print("Extracting frames from video...")
    run_ffmpeg(input_video, dirs["images"], fps=3)
    print(f"Frame extraction completed in {dirs['images']}.", end="\n\n")

    print("Starting COLMAP reconstruction...")
    run_colmap(dirs)
    print("COLMAP reconstruction completed.", end="\n\n")

    print("Starting Brush visualization...")
    run_brush(dirs, viewer=False, steps_count=3_000)
    print("Brush visualization completed.", end="\n\n")

    print("Cleaning up intermediate files...")
    cleanup(dirs)
    print("Cleanup completed.", end="\n\n")

    print("Process completed.")

    return {"splat_path": os.path.join(root_path, "splat.ply")}


def prepare_dirs(root_path: str):
    images = os.path.join(root_path, "images")

    if not os.path.exists(images):
        os.makedirs(images)

    colmap = os.path.join(root_path, "colmap")
    if not os.path.exists(colmap):
        os.makedirs(colmap)

    return {
        "images": images,
        "colmap": colmap,
        "workspace": root_path,
    }


def run_ffmpeg(
    input_file, output_directory, fps=5, max_size: tuple[int, int] = (1280, 720)
):
    return run(
        [
            ffmpeg_command,
            "-i",
            input_file,
            "-vf",
            f"scale={max_size[0]}:{max_size[1]}:force_original_aspect_ratio=decrease,fps={fps}",
            f"{output_directory}/frame_%04d.png",
        ]
    )


"""def run_colmap(paths: dict):
    return run(
        [
            colmap_command,
            "automatic_reconstructor",
            "--image_path",
            paths["images"],
            "--workspace_path",
            paths["colmap"],
        ]
    )"""


def run_colmap(paths: dict):
    # Use shell=True for xvfb-run in Docker
    cmd = f"{colmap_command} automatic_reconstructor --image_path {paths['images']} --workspace_path {paths['colmap']}"

    return run(
        cmd
        if IS_DOCKER
        else [
            colmap_path,
            "automatic_reconstructor",
            "--image_path",
            paths["images"],
            "--workspace_path",
            paths["colmap"],
        ],
        shell=IS_DOCKER,
    )


def run_brush(paths: dict, viewer: bool = False, steps_count: int = 3_000):
    args = [
        brush_command,
        paths["workspace"],
        "--export-path",
        paths["workspace"],
        "--export-name",
        "splat.ply",
        "--total-steps",
        str(steps_count),
    ]

    if viewer:
        args.append("--with-viewer")

    return run(" ".join(args) if IS_DOCKER else args, shell=IS_DOCKER)


def cleanup(paths: dict):
    shutil.rmtree(paths["colmap"], ignore_errors=True)
    shutil.rmtree(paths["images"], ignore_errors=True)


"""
def run(cmd: list[str], cwd: str | None = None):
    print("Running:", " ".join(cmd))
    subprocess.run(
        cmd, cwd=cwd, check=True, stdout=sys.stdout, stderr=sys.stderr, text=True
    )
"""


def run(cmd: list[str] | str, cwd: str | None = None, shell: bool = False):
    print(f"Running: {cmd if isinstance(cmd, str) else ' '.join(cmd)}", flush=True)
    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # Merge stderr into stdout
        text=True,
        bufsize=1,  # Line buffered
        shell=shell,
        universal_newlines=True,
    )

    # Stream output line by line in real-time
    if process.stdout is not None:
        for line in process.stdout:
            print(line, end="", flush=True)

    return_code = process.wait()

    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, cmd)

    return return_code
