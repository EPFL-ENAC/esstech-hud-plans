import os
import pty
import re
import select
import subprocess
import time
from typing import Callable, Literal, Union

import numpy as np
from api import runai
from api.config import config
from api.data_processing.splats import save_histogram
from api.models.splats import (
    BlueprintConfig,
    BrushTrainingConfig,
    ColmapAutoConfig,
    ColmapManualConfig,
    FFMPEGExtractionConfig,
    GenerationInputs,
)

from .pipeline_logger import PipelineLogger

RUNAI_POLL_INTERVAL = 10  # seconds
os.environ["PYTHONUNBUFFERED"] = "1"  # Add at top of file

# Check if running inside a Docker container
IS_DOCKER = os.path.exists("/.dockerenv")

backend_root = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

commands_prefix = os.path.join(backend_root, "external", "bin")
ffmpeg_command = os.path.join(commands_prefix, "ffmpeg")

# Determine colmap command based on environment
colmap_path = os.path.join(commands_prefix, "colmap")
colmap_command = f"xvfb-run -a {colmap_path}" if IS_DOCKER else colmap_path

brush_command = os.path.join(commands_prefix, "brush")

output_prefix = os.path.join(backend_root, "data", "splats")


class SplatPipeline:
    def __init__(self, job_name: str, inputs: GenerationInputs):
        self.job_name = job_name
        self.inputs = inputs
        steps_list = ["ffmpeg", "colmap", "brush"]
        if inputs.blueprint is not None:
            steps_list.append("blueprint_extraction")
        self.logger = PipelineLogger(
            name=job_name,
            initial_settings=inputs.dict(),
            steps_list=steps_list,
        )

        self.directories: dict[str, str] = {}

    def run(self):
        self.prepare_dirs(os.path.join(output_prefix, self.job_name))
        self.logger.set_file_path(
            os.path.join(self.directories["workspace"], "status.json")
        )
        self.logger.start()

        try:
            self.run_ffmpeg(
                self.inputs.video_path, self.directories["images"], self.inputs.ffmpeg
            )

            self.run_colmap(self.inputs.colmap)

            self.run_brush(self.inputs.brush)

            pipeline_output: dict[str, str | list[str] | list] = {
                "splat_path": os.path.join(self.directories["workspace"], "splat.ply"),
                "blueprints": [],
            }

            if self.inputs.blueprint is not None:
                self.extract_blueprint_from_splat(
                    os.path.join(self.directories["workspace"], "splat.ply"),
                    self.inputs.blueprint,
                    output_prefix=os.path.join(
                        self.directories["workspace"], "blueprint"
                    ),
                )
                pipeline_output["blueprints"] = [
                    os.path.join(self.directories["workspace"], "blueprint_top.png"),
                ]

            self.logger.complete(output=pipeline_output)

            return pipeline_output
        except Exception as e:
            self.logger.fail(message=str(e))
            raise e

    def prepare_dirs(self, root_path: str):
        images = os.path.join(root_path, "images")

        if not os.path.exists(images):
            os.makedirs(images)

        colmap = os.path.join(root_path, "colmap")
        if not os.path.exists(colmap):
            os.makedirs(colmap)

        self.directories = {
            "workspace": root_path,
            "images": images,
            "colmap": colmap,
        }

        return self.directories

    def run_ffmpeg(
        self, input_file: str, output_directory: str, cfg: FFMPEGExtractionConfig
    ):
        cmd: list[str] = [
            ffmpeg_command,
            "-i",
            input_file,
            "-vf",
            f"scale={cfg.fitInWidth}:{cfg.fitInHeight}:force_original_aspect_ratio=decrease,fps={cfg.fps}",
            f"{output_directory}/frame_%04d.png",
        ]

        self.logger.start_step("ffmpeg", settings=cfg.model_dump(), command=cmd)

        return self._run_command(
            cmd, step_name="ffmpeg", estimate_progress_callback=estimate_ffmpeg_progress
        )

    def run_colmap(self, cfg: Union[ColmapAutoConfig, ColmapManualConfig]):
        # Base arguments common to both
        args = [
            "automatic_reconstructor",
            "--image_path",
            os.path.relpath(self.directories["images"]),
            "--workspace_path",
            os.path.relpath(self.directories["colmap"]),
            "--camera_model",
            cfg.camera_model,
            "--dense",
            "0",
        ]

        if isinstance(cfg, ColmapAutoConfig):
            args.extend(
                [
                    "--data_type",
                    cfg.data_type,
                    "--quality",
                    cfg.quality,
                    "--single_camera",
                    "1" if cfg.single_camera else "0",
                    # "--max_image_size", str(cfg.max_image_size)
                ]
            )

        if config.USE_RUNAI:
            runai.copy_data_to_scratch(
                os.path.relpath(self.directories["images"]),
                os.path.relpath(self.directories["images"]),
            )
            runai.copy_data_to_scratch(
                os.path.relpath(self.directories["colmap"]),
                os.path.relpath(self.directories["colmap"]),
            )
            self._run_command_runai(
                args,
                step_name="colmap",
                estimate_progress_callback=estimate_colmap_progress,
            )
            runai.copy_data_from_scratch(
                os.path.relpath(self.directories["colmap"]),
                os.path.relpath(self.directories["colmap"]),
            )

        elif IS_DOCKER:
            # Use shell=True for xvfb-run in Docker
            cmd_str: str = f"{colmap_command} {' '.join(args)}"
            self.logger.start_step("colmap", settings=cfg.model_dump(), command=cmd_str)
            self._run_command(
                cmd_str,
                shell=True,
                step_name="colmap",
                estimate_progress_callback=estimate_colmap_progress,
            )

        else:
            cmd: list[str] = [colmap_path] + args
            self.logger.start_step("colmap", settings=cfg.model_dump(), command=cmd)
            self._run_command(
                cmd,
                step_name="colmap",
                estimate_progress_callback=estimate_colmap_progress,
            )

        # TODO: do one reconstruction per directory in `colmap/sparse`
        # based on config.MIN_COLMAP_IMAGES_KEEP
        sparse_dir = os.path.join(self.directories["colmap"], "sparse", "0")
        self._colmap_compute_geometric_data(sparse_dir)

    def _colmap_compute_geometric_data(self, sparse_dir: str):
        import pycolmap

        reconstruction = pycolmap.Reconstruction(sparse_dir)
        positions = []
        up_vectors = []

        sorted_image_ids = sorted(reconstruction.images.keys())

        for image_id in sorted_image_ids:
            image = reconstruction.images[image_id]
            pose = image.cam_from_world()

            translation = pose.translation
            rotation = pose.rotation.matrix()

            positions.append(-rotation.T @ translation)
            up_vectors.append(-rotation.T @ np.array([0, 1, 0]))

        positions = np.array(positions)
        up_vectors = np.array(up_vectors)
        average_up = np.mean(up_vectors, axis=0)

        # Find the normal to a plane fitted to the camera posisions
        center = np.mean(positions, axis=0)
        centered_positions = positions - center
        cov = np.cov(centered_positions, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eig(cov)
        normal = eigenvectors[:, np.argmin(eigenvalues)]
        tangent = eigenvectors[:, np.argmax(eigenvalues)]
        normal *= np.sign(np.dot(normal, average_up))
        normal /= np.linalg.norm(normal)
        world_rotation = np.stack([tangent, np.cross(normal, tangent), normal], axis=1)
        radius = np.max(np.linalg.norm(centered_positions, axis=1))

        self.logger.set_colmap_geometric_data(
            {
                "center": center.tolist(),
                "world_rotation": world_rotation.tolist(),
                "radius": radius,
                "positions": positions.tolist(),
            }
        )

    def run_brush(self, cfg: BrushTrainingConfig):
        args = [
            brush_command,
            os.path.relpath(self.directories["workspace"]),
            "--export-path",
            os.path.relpath(self.directories["workspace"]),
            "--export-name",
            "splat.ply",
            "--total-steps",
            str(cfg.totalSteps),
            "--render-mode",
            cfg.renderMode,
            "--sh-degree",
            str(cfg.shDegree),
            "--max-splats",
            str(cfg.maxSplats),
            "--refine-every",
            str(cfg.refineEvery),
            "--growth-grad-threshold",
            str(cfg.growthGradThreshold),
            "--growth-stop-iter",
            str(cfg.growthStopIter),
            "--max-resolution",
            str(cfg.maxResolution),
            "--subsample-frames",
            str(cfg.subsampleFrames),
            "--alpha-mode",
            cfg.alphaMode,
        ]

        if config.USE_RUNAI:
            runai.copy_data_to_scratch(
                os.path.relpath(self.directories["workspace"]),
                os.path.relpath(self.directories["workspace"]),
            )
            self._run_command_runai(
                args,
                step_name="brush",
                estimate_progress_callback=estimate_training_progress,
            )
            runai.copy_data_from_scratch(
                os.path.relpath(self.directories["workspace"]),
                os.path.relpath(self.directories["workspace"]),
            )
        elif IS_DOCKER:
            command: str = " ".join(args)
            self.logger.start_step("brush", settings=cfg.model_dump(), command=command)
            return self._run_command(
                command,
                shell=True,
                step_name="brush",
                estimate_progress_callback=estimate_training_progress,
            )
        else:
            self.logger.start_step("brush", settings=cfg.model_dump(), command=args)
            return self._run_command(
                args,
                shell=False,
                step_name="brush",
                estimate_progress_callback=estimate_training_progress,
            )

    def compute_blueprint_view_matrix(
        self, colmap_geometry: dict, distance_scale: float = 1000.0
    ) -> np.ndarray:
        """Compute the 4x4 view matrix for the blueprint top-down view.

        Args:
            colmap_geometry: Dictionary with 'center', 'world_rotation', and 'radius' keys
            distance_scale: Multiplier for radius to determine view distance (default: 1000.0)

        Returns:
            4x4 numpy array representing the view matrix
        """
        center = np.array(colmap_geometry["center"])
        world_rotation = np.array(colmap_geometry["world_rotation"])
        radius = colmap_geometry["radius"]

        D = distance_scale * radius  # Large distance to flatten perspective

        # Top-down view rotation matrix (converts from world space to top-down view)
        R_td = np.array([[1, 0, 0], [0, -1, 0], [0, 0, 1]], dtype=np.float32)
        R_combined = R_td @ world_rotation.T
        t_combined = -R_combined @ center
        t_combined[2] += D

        view_mat = np.eye(4, dtype=np.float32)
        view_mat[:3, :3] = R_combined
        view_mat[:3, 3] = t_combined

        return view_mat

    def extract_blueprint_from_splat(
        self, ply_path: str, cfg: BlueprintConfig, output_prefix: str = "blueprint"
    ):
        try:
            import torch
            from gsplat import rasterization
            from PIL import Image
            from plyfile import PlyData

        except ImportError as e:
            self.logger.step_failed(
                "blueprint_extraction",
                "Required libraries for blueprint extraction are missing. Please install the [blueprint] extras.",
            )
            return

        import numpy as np

        DISTANCE_SCALE = 1000.0

        colmap_geometry = self.logger.get_colmap_geometric_data()
        if colmap_geometry is None:
            self.logger.fail("Cannot extract blueprint without COLMAP geometric data.")
            return

        radius = colmap_geometry["radius"]

        self.logger.start_step("blueprint_extraction")

        plydata = PlyData.read(ply_path)
        v = plydata["vertex"]

        means = np.stack([v["x"], v["y"], v["z"]], axis=-1)
        means = torch.from_numpy(means).float().cuda()

        scales = np.stack([v["scale_0"], v["scale_1"], v["scale_2"]], axis=-1)
        scales = torch.exp(torch.from_numpy(scales).float().cuda())

        quats = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=-1)
        quats = torch.from_numpy(quats).float().cuda()

        opacities = v["opacity"][:, np.newaxis] + cfg.opacityShift
        opacities = (
            torch.sigmoid(torch.from_numpy(opacities).float().cuda()) * cfg.opacity
        )

        sh_dc = np.stack([v["f_dc_0"], v["f_dc_1"], v["f_dc_2"]], axis=-1)
        colors = torch.sigmoid(torch.from_numpy(sh_dc))
        colors = colors.float().cuda()

        self.logger.add_log(
            "blueprint_extraction",
            f"Loaded point cloud with {len(v)} points from {ply_path}.",
        )
        self.logger.update_step_progress("blueprint_extraction", 0.0)

        center = torch.tensor(
            colmap_geometry["center"], device="cuda", dtype=torch.float32
        )

        view_mat_np = self.compute_blueprint_view_matrix(
            colmap_geometry, distance_scale=DISTANCE_SCALE
        )
        view_mat = torch.from_numpy(view_mat_np).cuda()

        D = DISTANCE_SCALE * radius
        focal_obj = (cfg.imageWidth / 2) / (radius * cfg.radiusScale)
        focal_length = focal_obj * D
        K = torch.tensor(
            [
                [focal_length, 0, cfg.imageWidth / 2],
                [0, focal_length, cfg.imageHeight / 2],
                [0, 0, 1],
            ],
            device="cuda",
            dtype=torch.float32,
        )

        render_colors, render_alphas, info = rasterization(
            means=means,
            quats=quats,
            scales=scales,
            opacities=opacities.squeeze(-1),
            colors=colors,
            viewmats=view_mat[None, ...],
            Ks=K[None, ...],
            width=cfg.imageWidth,
            height=cfg.imageHeight,
            near_plane=D - cfg.verticalClip * radius,
            far_plane=D + cfg.verticalClip * radius,
        )

        self.logger.update_step_progress("blueprint_extraction", 1.0)

        self.logger.add_log(
            "blueprint_extraction",
            f"Finished processing points. Saving blueprint image to {output_prefix}_top.png",
        )

        img = Image.fromarray(
            ((1 - render_alphas[0].cpu().numpy()) * 255).astype(np.uint8).squeeze()
        )
        # img = Image.fromarray((render_colors[0].cpu().numpy() * 255).astype(np.uint8))
        img.save(f"{output_prefix}_top.png")

        self.logger.step_completed("blueprint_extraction")

    def _run_command(
        self,
        cmd: list[str] | str,
        cwd: str | None = None,
        shell: bool = False,
        step_name: str | None = None,
        estimate_progress_callback: Callable[[str], float] | None = None,
    ):
        if step_name is not None:
            self.logger.add_log(
                step_name,
                f"Running command: {cmd if isinstance(cmd, str) else ' '.join(cmd)}",
                heading_level=1,
            )
        # Use a pseudo-terminal to trick the process into thinking it's interactive
        master, slave = pty.openpty()

        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=slave,
            stderr=slave,
            stdin=slave,
            shell=shell,
            close_fds=True,
        )

        os.close(slave)

        def log_and_estimate_progress(line: str):
            if step_name is None:
                return
            self.logger.add_log(
                step_name, line, cleanup_for_file=_extract_meaningful_log
            )
            if estimate_progress_callback is not None:
                self.logger.update_step_progress(
                    step_name,
                    estimate_progress_callback(
                        self.logger.get_full_log_from_step(step_name)
                    ),
                )

        # Read from master in non-blocking mode
        buffer = ""
        while True:
            try:
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        data = os.read(master, 1024).decode("utf-8", errors="replace")
                        if not data:
                            break

                        buffer += data
                        lines = buffer.split("\n")
                        buffer = lines[-1]

                        for line in lines[:-1]:
                            if step_name is not None and line.strip():
                                log_and_estimate_progress(line.rstrip("\r"))

                        # Also log progress updates (lines ending with \r but no \n)
                        if "\r" in buffer and step_name is not None:
                            parts = buffer.split("\r")
                            for part in parts[:-1]:
                                if part.strip():
                                    log_and_estimate_progress(part)
                            buffer = parts[-1]

                    except OSError:
                        break

                # Check if process has finished
                if process.poll() is not None:
                    # Read any remaining data
                    try:
                        while True:
                            data = os.read(master, 1024).decode(
                                "utf-8", errors="replace"
                            )
                            if not data:
                                break
                            if step_name is not None:
                                log_and_estimate_progress(data.rstrip("\n\r"))
                    except OSError:
                        pass
                    break
            except KeyboardInterrupt:
                process.terminate()
                break

        os.close(master)
        return_code = process.wait()

        if return_code != 0:
            raise subprocess.CalledProcessError(return_code, cmd)

        if step_name is not None:
            self.logger.add_log(
                step_name,
                f"Command completed with return code {return_code}",
                heading_level=3,
            )
            self.logger.step_completed(step_name, return_code=return_code)

        return return_code

    def _run_command_runai(
        self,
        cmd: list[str],
        step_name: Literal["ffmpeg", "colmap", "brush"],
        estimate_progress_callback: Callable[[str], float],
    ):
        job_name = runai.submit_job(tool=step_name, command=cmd)
        log_file_path = runai.get_log_file_path(job_name)

        def log_and_estimate_progress(line: str):
            self.logger.add_log(
                step_name, line, cleanup_for_file=_extract_meaningful_log
            )
            self.logger.update_step_progress(
                step_name,
                estimate_progress_callback(
                    self.logger.get_full_log_from_step(step_name)
                ),
            )

        while not os.path.exists(log_file_path):
            if runai.check_job_terminated(job_name) is not False:
                self.logger.step_failed(
                    step_name,
                    f"RunAI job {job_name} terminated before log file was created.",
                )
                return
            time.sleep(RUNAI_POLL_INTERVAL)

        with open(log_file_path, "r", encoding="utf-8", errors="replace") as f:
            buffer = ""
            while True:
                chunk = f.read(1024)
                if chunk:
                    buffer += chunk
                    lines = buffer.split("\n")
                    # Keep the last (potentially incomplete) line in the buffer
                    buffer = lines[-1]
                    for line in lines[:-1]:
                        if line.strip():
                            log_and_estimate_progress(line.rstrip("\r"))
                else:
                    # No new data — flush any remaining buffered content if job is done
                    if runai.check_job_terminated(job_name) is not False:
                        if buffer.strip():
                            log_and_estimate_progress(buffer.rstrip("\r"))
                        break
                    time.sleep(RUNAI_POLL_INTERVAL)

        self.logger.add_log(
            step_name,
            "Command completed",
            heading_level=3,
        )
        self.logger.step_completed(step_name)


def _extract_meaningful_log(line: str) -> str | None:
    if line is None:
        return None

    # 1. Remove ANSI escape sequences
    line = re.sub(r"\x1b\[[0-9;]*[mKABCDEFG]", "", line)

    # 2. Aggressive Symbol & Emoji Removal
    # This covers:
    # \u2000-\u2bff: General Symbols, Arrows, Math, Punctuation, Circles, Checks
    # \ud800-\udfff: Surrogate pairs (most emojis like paintbrush)
    # \ufe00-\ufe0f: Variation selectors
    symbol_pattern = r"[\u2000-\u2bff\ud800-\udfff\ufe00-\ufe0f\u00b7]"
    line = re.sub(symbol_pattern, "", line)
    line = line.replace(r"\ud83d\udd8c", "")
    line = line.replace("\U0001f58c", "")

    # 3. Filter out known "Noise" sentences
    # We do this AFTER removing symbols so the regex is simpler
    noise_patterns = [
        r"evaluating every \d+ steps",
        r"^\s*$",
    ]
    for pattern in noise_patterns:
        if re.search(pattern, line, re.IGNORECASE):
            return None

    # 4. Cleanup Whitespace
    line = re.sub(r"\s{2,}", " ", line).strip()

    # 5. Meaningless Status-only lines
    # If the line is JUST one of these words, it's noise.
    # If it's "Training 5/100", we keep it (or the loop below strips the prefix).
    meaningless_phrases = ["Training", "Completed loading", "Starting up"]

    if line in meaningless_phrases:
        return None

    # 6. Strip redundant prefixes
    # e.g., "Starting up Loading dataset..." -> "Loading dataset..."
    for phrase in meaningless_phrases:
        if line.startswith(phrase):
            temp = line[len(phrase) :].strip()
            if temp:
                line = temp

    # Remove the [0s] time markers
    line = re.sub(r"\[\d+s\]", "", line).strip()

    # Final check: is there anything left?
    if not line or len(line) < 2:
        return None

    return line


def estimate_ffmpeg_progress(log_text: str) -> float:
    """
    Estimates the progress (0.0 to 1.0) of an FFmpeg process
    by comparing current timestamp to total duration.
    """

    def get_seconds(time_str: str) -> float:
        """Converts HH:MM:SS.ms to total seconds."""
        h, m, s = time_str.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    # 1. Find the total duration of the input video
    # Pattern looks for: Duration: 00:00:06.83
    duration_match = re.search(r"Duration:\s+(\d{2}:\d{2}:\d{2}\.\d{2})", log_text)
    if not duration_match:
        return 0.0

    total_seconds = get_seconds(duration_match.group(1))
    if total_seconds <= 0:
        return 0.0

    # 2. Find all 'time=' markers and take the latest one
    # Pattern looks for: time=00:00:01.50
    time_matches = re.findall(r"time=(\d{2}:\d{2}:\d{2}\.\d{2})", log_text)

    if not time_matches:
        # Check if the process finished (indicated by 'Lsize=' or 'video:XKiB')
        if "video:" in log_text and "muxing overhead" in log_text:
            return 1.0
        return 0.0

    current_seconds = get_seconds(time_matches[-1])

    # 3. Calculate ratio
    progress = current_seconds / total_seconds

    # Cap at 1.0 (sometimes FFmpeg time slightly exceeds duration due to padding)
    return min(max(progress, 0.0), 1.0)


def estimate_colmap_progress(log_text: str) -> float:
    """
    Estimates the progress (0.0 to 1.0) of a COLMAP automatic reconstruction
    based on log output.
    """
    # 1. Determine the total number of images
    # Look for "Processed file [X/Y]" patterns
    total_images_match = re.findall(r"Processed file \[\d+/(\d+)\]", log_text)
    total_images = int(total_images_match[-1]) if total_images_match else 0

    # 2. Check current stage
    # Stages: Extraction ~0-30%, Matching ~30-40%, Mapping ~40-100%

    # Check if Mapping has started
    if "incremental_pipeline.cc" in log_text or "Registering image" in log_text:
        # Find the highest "num_reg_frames=X"
        reg_frames = re.findall(r"num_reg_frames=(\d+)", log_text)
        if reg_frames and total_images > 0:
            current_reg = int(reg_frames[-1])
            # Mapping takes the bulk of the remaining 60% of the progress bar
            # We map the registered count from 0-total to 0.4-1.0
            mapping_progress = current_reg / total_images
            return min(0.4 + (mapping_progress * 0.6), 1.0)
        return 0.4

    # Check if Matching has started
    if "Feature matching & geometric verification" in log_text:
        # Matching is usually fast relative to others, we'll place it at 30-40%
        return 0.35

    # Check if Extraction is in progress
    if "Feature extraction" in log_text:
        if total_images_match and total_images > 0:
            # Get the current file index [X/Y]
            current_file_idx = int(re.findall(r"Processed file \[(\d+)/", log_text)[-1])
            # Extraction represents the first 30%
            extraction_progress = current_file_idx / total_images
            return extraction_progress * 0.3
        return 0.1

    # Check for completion
    if (
        "Command completed" in log_text
        or "Keeping successful reconstruction" in log_text
    ):
        return 1.0

    return 0.0


import re


def estimate_training_progress(log_text: str) -> float:
    """
    Estimates progress (0.0 to 1.0) for training processes
    using the 'Step/Total Steps' format.
    """
    # Pattern to find the last occurrence of "current/total Steps"
    # Example: "995/1000 Steps"
    step_matches = re.findall(r"(\d+)/(\d+)\s+Steps", log_text)

    if not step_matches:
        # Fallback: Check if the training is explicitly finished
        if "Training took" in log_text or "Completed" in log_text:
            return 1.0
        return 0.0

    # Get the last match found in the log
    current_step_str, total_steps_str = step_matches[-1]

    current_step = float(current_step_str)
    total_steps = float(total_steps_str)

    if total_steps <= 0:
        return 0.0

    progress = current_step / total_steps

    # If the log shows "Training took X", ensure it returns 1.0
    # even if the steps count hasn't updated yet.
    if "Training took" in log_text:
        return 1.0

    return min(max(progress, 0.0), 1.0)
