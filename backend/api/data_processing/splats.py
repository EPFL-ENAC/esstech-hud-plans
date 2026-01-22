import os
import shutil
import subprocess
import sys

backend_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

commands_prefix = os.path.join(backend_root, "external", "bin")
ffmpeg_command = "ffmpeg"
colmap_command = f"xvfb-run -a {os.path.join(commands_prefix, 'colmap')}"
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


def run_colmap(paths: dict):
    return run(
        [
            colmap_command,
            "automatic_reconstructor",
            "--image_path",
            paths["images"],
            "--workspace_path",
            paths["colmap"],
        ]
    )


def run_brush(paths: dict, viewer: bool = False, steps_count: int = 10_000):
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

    return run(args)


def cleanup(paths: dict):
    shutil.rmtree(paths["colmap"], ignore_errors=True)
    shutil.rmtree(paths["images"], ignore_errors=True)


def run(cmd: list[str], cwd: str | None = None):
    print("Running:", " ".join(cmd))
    subprocess.run(
        cmd, cwd=cwd, check=True, stdout=sys.stdout, stderr=sys.stderr, text=True
    )
