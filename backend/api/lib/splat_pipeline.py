import logging
import os
import pty
import re
import select
import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Literal, Union

import numpy as np
from api import runai
from api.config import config
from api.lib.compute.colmap_geometric_data import (
    ColmapGeometricData,
    colmap_compute_geometric_data,
    compute_blueprint_view_matrix,
)
from api.models.splats import (
    BaseGenerationInputs,
    BlueprintConfig,
    BrushTrainingConfig,
    ColmapAutoConfig,
    ColmapManualConfig,
    FFMPEGExtractionConfig,
    FrameExtractionConfig,
    GenerationInputs,
    SmartExtractionConfig,
)

from .pipeline_logger import PipelineLogger

logger = logging.getLogger("uvicorn.error")

RUNAI_POLL_INTERVAL = 5  # seconds
RUNAI_CHECK_STATUS_MAX_FAILS = 5
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


class BasePipeline(ABC):
    def __init__(self, job_name: str, inputs: BaseGenerationInputs):
        self.job_name = job_name
        self.inputs = inputs

        steps_list = []
        if inputs.frame_extraction is not None:
            steps_list.append("ffmpeg")
            if inputs.frame_extraction.mode == "smart":
                steps_list.append("frame_picker")
        if inputs.colmap is not None:
            steps_list.append("colmap")
        if inputs.brush is not None:
            steps_list.append("brush")
        if inputs.blueprint is not None:
            steps_list.append("blueprint_extraction")

        self.logger = PipelineLogger(
            name=job_name,
            initial_settings=inputs.dict(),
            steps_list=steps_list,
        )

        self.directories: dict[str, str] = {}

    @abstractmethod
    def prepare_dirs(self, root_path: str):
        pass

    @abstractmethod
    def _run(self) -> dict[str, str | list[str] | list]:
        pass

    def run(self):
        self.prepare_dirs(os.path.join(output_prefix, self.job_name))
        return self._run()

    def run_ffmpeg(
        self,
        input_file: str,
        output_directory: str,
        cfg: FFMPEGExtractionConfig,
    ):
        # Prepare the filter chain
        filters = f"scale={cfg.fitInWidth}:{cfg.fitInHeight}:force_original_aspect_ratio=decrease"

        # Append fps filter only if a value is provided
        if cfg.fps is not None and cfg.fps > 0:
            filters += f",fps={cfg.fps}"

        cmd: list[str] = [
            ffmpeg_command,
            "-i",
            input_file,
            "-vf",
            filters,
            f"{output_directory}/frame_%04d.png",
        ]

        self.logger.start_step("ffmpeg", settings=cfg.model_dump(), command=cmd)

        return self._run_command(
            cmd,
            step_name="ffmpeg",
            estimate_progress_callback=estimate_ffmpeg_progress,
        )

    def run_frame_picker(
        self,
        video_source_path: str,
        input_frames: str,
        output_directory: str,
        cfg: SmartExtractionConfig,
    ):
        from api.lib.compute.evaluate_video_frame import pick_frames

        def on_progress(msg: str, progress: float | None = None):
            self.logger.add_log("frame_picker", msg)
            if progress is not None:
                self.logger.update_step_progress("frame_picker", progress)

        self.logger.start_step("frame_picker", settings=cfg.model_dump())
        self.logger.add_log("frame_picker", "Evaluating frames for selection...")
        evaluation = pick_frames(
            video_source_path,
            input_frames,
            output_directory,
            distance_threshold=cfg.distance_threshold,
            min_fps=cfg.min_fps,
            remove_outliers=cfg.remove_outliers,
            outlier_window_size=7,
            outlier_sharpness_ratio=getattr(cfg, "outlier_sharpness_ratio", 0.5),
            output_symlink_relative_to=self.directories["workspace"],
            on_progress=on_progress,
        )
        self.logger.add_log(
            "frame_picker", f"Selected {len(evaluation)} frames after evaluation."
        )
        self.logger.step_completed("frame_picker")

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
            if cfg.use_global_mapper:
                args.extend(["--mapper", "global"])

        if config.USE_RUNAI:
            runai.copy_data_to_scratch(
                os.path.relpath(self.directories["workspace"]),
                os.path.relpath(self.directories["workspace"]),
            )
            cmd = ["xvfb-run", "-a", "colmap"] + args
            self.logger.submit_step("colmap", settings=cfg.model_dump(), command=cmd)
            self._run_command_runai(
                cmd,
                step_name="colmap",
                estimate_progress_callback=estimate_colmap_progress,
            )
            runai.copy_data_from_scratch(
                os.path.relpath(self.directories["workspace"]),
                os.path.relpath(self.directories["workspace"]),
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
            cmd = [colmap_path] + args
            self.logger.start_step("colmap", settings=cfg.model_dump(), command=cmd)
            self._run_command(
                cmd,
                step_name="colmap",
                estimate_progress_callback=estimate_colmap_progress,
            )

        if self.logger.has_failed("colmap"):
            return

        sparse_dir = os.path.join(self.directories["colmap"], "sparse")
        if not os.path.exists(sparse_dir):
            self.logger.step_failed(
                "colmap",
                f"Expected COLMAP output directory not found: {sparse_dir}",
            )
            return

        sparse_dir_0 = os.path.join(sparse_dir, "0")
        if not os.path.exists(sparse_dir_0):
            self.logger.step_failed(
                "colmap",
                f"Expected COLMAP sparse reconstruction directory not found: {sparse_dir_0}",
            )
            return

        self._colmap_evaluate_reconstruction()

        self._colmap_compute_geometric_data(sparse_dir_0)

    def _colmap_evaluate_reconstruction(self) -> dict:
        from api.lib.compute.evaluate_colmap import evaluate_sparse_reconstructions

        sparse_dir = os.path.join(self.directories["colmap"], "sparse")
        frames_count = (
            len(
                [
                    f
                    for f in os.listdir(self.directories["images"])
                    if os.path.isfile(os.path.join(self.directories["images"], f))
                ]
            )
            if os.path.exists(self.directories["images"])
            else None
        )

        evaluation = evaluate_sparse_reconstructions(
            sparse_dir, total_input_frames=frames_count
        )
        self._colmap_postprocess()
        self._colmap_pick_reconstruction(
            evaluation.evaluations[evaluation.best_model_index].metrics.model_name
        )

        self.logger.evaluate_step("colmap", evaluation.model_dump(mode="json"))
        return evaluation

    def _colmap_postprocess(self):
        sparse_dir = os.path.join(self.directories["colmap"], "sparse")
        reconstructions_folder = [f for f in Path(sparse_dir).iterdir() if f.is_dir()]
        if len(reconstructions_folder) < 2:
            self.logger.add_log(
                "colmap",
                "Only one reconstruction found, skipping post-processing.",
            )
            return

        for folder in reconstructions_folder:
            if folder.name.isdigit():
                new_name = f"original_{folder.name}"
                new_path = folder.with_name(new_name)

                # Safety check: don't overwrite if original_X already exists
                if not new_path.exists():
                    folder.rename(new_path)

    def _colmap_pick_reconstruction(self, reconstruction: int | str):
        reconstruction = str(reconstruction)
        sparse_dir = os.path.join(self.directories["colmap"], "sparse")

        picked_path = os.path.join(sparse_dir, "0")

        if os.path.exists(picked_path):
            if os.path.islink(picked_path):
                os.unlink(picked_path)
            else:
                return  # We expect "0" to be a symlink to the chosen reconstruction. If it's not a symlink, it means there is only 1 reconstruction and it's already in place, so we do nothing.

        os.symlink(
            os.path.join(sparse_dir, f"original_{reconstruction}"),
            picked_path,
            target_is_directory=True,
        )
        self.logger.add_log(
            "colmap",
            f"Selected reconstruction {reconstruction} and created symlink at {picked_path}",
        )

    def _colmap_compute_geometric_data(self, sparse_dir: str):
        colmap_data = colmap_compute_geometric_data(sparse_dir)
        self.logger.set_colmap_geometric_data(colmap_data.model_dump(mode="json"))

    def run_brush(self, cfg: BrushTrainingConfig):
        workspace_dir = (
            os.path.relpath(self.directories["workspace"])
            if config.USE_RUNAI
            else os.path.abspath(self.directories["workspace"])
        )

        args = [
            brush_command,
            workspace_dir,
            "--export-path",
            workspace_dir,
            "--export-name",
            "splat.ply",
            "--total-train-iters",
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
                workspace_dir,
                workspace_dir,
            )
            args[3] = os.path.join(
                "/scratch", args[3]
            )  # workspace path must be absolute
            cmd = ["brush"] + args[1:]
            self.logger.submit_step("brush", settings=cfg.model_dump(), command=cmd)
            self._run_command_runai(
                cmd,
                step_name="brush",
                estimate_progress_callback=estimate_training_progress,
            )
            runai.copy_data_from_scratch(
                workspace_dir,
                workspace_dir,
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
        return compute_blueprint_view_matrix(
            ColmapGeometricData(**colmap_geometry), distance_scale
        )

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

        buffer = ""
        read_pos = 0
        runai_check_fails = 0

        while runai_check_fails < RUNAI_CHECK_STATUS_MAX_FAILS:
            if not self.logger.has_started(step_name) and runai.check_job_started(
                job_name
            ):
                self.logger.start_step(step_name)

            runai.refresh_logs()
            try:
                with open(log_file_path, "rb") as f:
                    f.seek(read_pos)
                    raw_chunk = f.read()
                    read_pos = f.tell()

                    chunk = raw_chunk.decode("utf-8", errors="replace")
                    buffer += chunk
                    lines = buffer.split("\n")
                    buffer = lines[-1]
                    for line in lines[:-1]:
                        if line.strip():
                            log_and_estimate_progress(line.rstrip("\r"))
                    if "\r" in buffer:
                        parts = buffer.split("\r")
                        for part in parts[:-1]:
                            if part.strip():
                                log_and_estimate_progress(part)
                        buffer = parts[-1]

            except Exception as e:
                pass

            runai_check_terminated = runai.check_job_terminated(job_name)

            if runai_check_terminated:
                if buffer.strip():
                    log_and_estimate_progress(buffer.rstrip("\r"))
                break

            if runai_check_terminated is None:
                runai_check_fails += 1

            time.sleep(RUNAI_POLL_INTERVAL)

        if runai_check_fails >= RUNAI_CHECK_STATUS_MAX_FAILS:
            self.logger.step_failed(
                step_name,
                f"Failed to get status from RunAI after {RUNAI_CHECK_STATUS_MAX_FAILS} attempts.",
            )
            return

        self.logger.add_log(
            step_name,
            "Command completed with return code 0",
            heading_level=3,
        )
        self.logger.step_completed(step_name, return_code=0)


class SplatPipeline(BasePipeline):
    def __init__(self, job_name: str, inputs: GenerationInputs):
        self.inputs: GenerationInputs
        super().__init__(job_name=job_name, inputs=inputs)

    def prepare_dirs(self, root_path: str):
        images = os.path.join(root_path, "images")
        if not os.path.exists(images):
            os.makedirs(images)

        images_raw = os.path.join(root_path, "images_raw")
        if not os.path.exists(images_raw):
            os.makedirs(images_raw)

        colmap = os.path.join(root_path, "colmap")
        if not os.path.exists(colmap):
            os.makedirs(colmap)

        self.directories = {
            "workspace": root_path,
            "images": images,
            "images_raw": images_raw,
            "colmap": colmap,
        }

    def _run(self) -> dict[str, str | list[str] | list]:
        self.logger.set_file_path(
            os.path.join(self.directories["workspace"], "status.json")
        )
        self.logger.start()

        try:
            if self.inputs.frame_extraction.mode == "smart":
                self.run_ffmpeg(
                    self.inputs.video_path,
                    self.directories["images_raw"],
                    FFMPEGExtractionConfig(
                        fitInWidth=self.inputs.frame_extraction.fitInWidth,
                        fitInHeight=self.inputs.frame_extraction.fitInHeight,
                    ),
                )
                self.run_frame_picker(
                    self.inputs.video_path,
                    self.directories["images_raw"],
                    self.directories["images"],
                    self.inputs.frame_extraction,
                )
            else:
                self.run_ffmpeg(
                    self.inputs.video_path,
                    self.directories["images"],
                    FFMPEGExtractionConfig(
                        fitInWidth=self.inputs.frame_extraction.fitInWidth,
                        fitInHeight=self.inputs.frame_extraction.fitInHeight,
                        fps=self.inputs.frame_extraction.fps,
                    ),
                )

            self.run_colmap(self.inputs.colmap)
            if self.logger.has_failed("colmap"):
                self.logger.fail(
                    message=f"COLMAP reconstruction failed. Aborting pipeline. {self.logger.get_fail_message('colmap')}"
                )
                return {
                    "splat_path": "",
                    "blueprints": [],
                }

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
