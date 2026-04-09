import json
import os
import sys
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from typing import Union

from api.lib.restart_brush_pipeline import RestartBrushPipeline
from api.lib.splat_pipeline import SplatPipeline
from api.models.splats import (
    BrushTrainingConfig,
    ColmapAutoConfig,
    ColmapManualConfig,
    FFMPEGExtractionConfig,
    GenerationInputs,
    RestartBrushInputs,
)

# Add parent directory to path to import other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class GenerationRun:
    id: str
    status: str  # "pending", "completed", "failed"
    input_video_path: str
    output_splat_path: str | None = None


class GenerationManager:
    def __init__(self):
        self.runs: dict[str, GenerationRun] = {}

        self.executor = ProcessPoolExecutor()
        self.futures: dict[str, Future] = {}

    def run_generation(self, inputs: GenerationInputs) -> GenerationRun:
        id = uuid.uuid4().hex
        run = GenerationRun(id=id, input_video_path=inputs.video_path, status="pending")
        self.runs[id] = run

        future = self.executor.submit(_run_generation, inputs, run.id)
        self.futures[id] = future

        def _on_done(fut):
            if fut.exception() is not None:
                run.status = "failed"
            else:
                run.status = "completed"
                run.output_splat_path = fut.result()["splat_path"]

            self.futures.pop(run.id)

        future.add_done_callback(_on_done)

        return run

    def get_run(self, generation_id: str) -> GenerationRun | None:
        run = self.runs.get(generation_id)
        if run is not None:
            if run.status != "completed":
                return None
            return run

        # Check if generation exists on disk after restart
        splat_dir = self._make_generation_folder_path(generation_id)
        status_file = os.path.join(splat_dir, "status.json")

        if not os.path.exists(status_file):
            return None

        try:
            with open(status_file, "r") as f:
                data = json.load(f)

            overall_status = data.get("overall_status", "pending")
            output = data.get("output", {})
            settings = data.get("settings", {})

            # Determine status: treat unfinished runs as failed
            if overall_status == "completed":
                status = "completed"
            else:
                status = "failed"

            # Reconstruct the run from disk
            run = GenerationRun(
                id=generation_id,
                status=status,
                input_video_path=settings.get("video_path", ""),
                output_splat_path=output.get("splat_path")
                if status == "completed"
                else None,
            )
            self.runs[generation_id] = run
            return run if status == "completed" else None

        except (json.JSONDecodeError, IOError):
            return None

    def _get_default_steps_list(self, settings: dict) -> list[str]:
        """Determine the default steps list based on settings."""
        steps = ["ffmpeg", "colmap", "brush"]
        # Check if blueprint was enabled in settings
        blueprint_settings = settings.get("blueprint")
        if blueprint_settings is not None:
            steps.append("blueprint_extraction")
        return steps

    def get_status(self, generation_id: str) -> dict:
        # read the file "status.json" in the workspace of the generation run
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        file = os.path.join(backend_root, f"data/splats/{generation_id}/status.json")

        if not os.path.exists(file):
            return {
                "overall_status": "pending",
                "name": generation_id,
                "progress": 0,
                "message": "Initializing pipeline...",
                "started_at": None,
                "finished_at": None,
                "output": None,
                "settings": {},
                "steps_list": ["ffmpeg", "colmap", "brush"],
                "steps": {},
            }

        try:
            with open(file, "r") as f:
                data = json.load(f)
            return data
        except json.JSONDecodeError:
            return {
                "overall_status": "pending",
                "name": generation_id,
                "progress": 0,
                "message": "Reading status...",
                "started_at": None,
                "finished_at": None,
                "output": None,
                "settings": {},
                "steps_list": ["ffmpeg", "colmap", "brush"],
                "steps": {},
            }
        except IOError as e:
            return {
                "overall_status": "pending",
                "name": generation_id,
                "progress": 0,
                "message": "Waiting for status file...",
                "started_at": None,
                "finished_at": None,
                "output": None,
                "settings": {},
                "steps_list": ["ffmpeg", "colmap", "brush"],
                "steps": {},
            }

    def get_blueprints(self, generation_id: str) -> dict[str, str | None]:
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        blueprint_prefix = os.path.join(
            backend_root, f"data/splats/{generation_id}/blueprint"
        )

        views: dict[str, str | None] = {
            "top": f"{blueprint_prefix}_top.png",
            "bottom": f"{blueprint_prefix}_bottom.png",
            "front": f"{blueprint_prefix}_front.png",
            "back": f"{blueprint_prefix}_back.png",
            "left": f"{blueprint_prefix}_left.png",
            "right": f"{blueprint_prefix}_right.png",
        }

        for key, path in list(views.items()):
            if path is not None and not os.path.exists(path):
                views[key] = None

        return views

    def get_colmap_geometry(self, generation_id: str) -> dict | None:
        """Retrieve the COLMAP geometric data for a generation run."""
        status = self.get_status(generation_id)
        return status.get("colmap_geometric_data")

    def get_settings(self, generation_id: str) -> dict | None:
        """Retrieve the settings for a generation run."""
        status = self.get_status(generation_id)
        return status.get("settings")

    def get_interactive_blueprint_params(self, generation_id: str) -> dict | None:
        """Retrieve the interactive blueprint parameters for a generation run."""
        status = self.get_status(generation_id)
        return status.get("interactive_blueprint_params")

    def save_interactive_blueprint_params(
        self, generation_id: str, params: dict
    ) -> bool:
        """Save the interactive blueprint parameters for a generation run."""
        status = self.get_status(generation_id)
        status["interactive_blueprint_params"] = params

        return self._save_status(generation_id, status)

    def get_generation_feedback(self, generation_id: str) -> dict | None:
        """Retrieve the generation feedback for a generation run."""
        status = self.get_status(generation_id)
        return status.get("generation_feedback")

    def save_generation_feedback(self, generation_id: str, feedback: dict) -> bool:
        """Save the generation feedback for a generation run."""
        status = self.get_status(generation_id)
        status["generation_feedback"] = feedback

        return self._save_status(generation_id, status)

    def run_restart_brush(self, inputs: RestartBrushInputs) -> GenerationRun:
        new_id = uuid.uuid4().hex
        run = GenerationRun(id=new_id, input_video_path="", status="pending")
        self.runs[new_id] = run

        future = self.executor.submit(_run_restart_brush, inputs, new_id)
        self.futures[new_id] = future

        def _on_done(fut):
            if fut.exception() is not None:
                run.status = "failed"
            else:
                run.status = "completed"
                run.output_splat_path = fut.result()["splat_path"]
            self.futures.pop(new_id)

        future.add_done_callback(_on_done)

        return run

    def evaluate_colmap_reconstruction(self, generation_id: str):
        from api.lib.compute.evaluate_colmap import evaluate_sparse_reconstructions

        folder = self._make_generation_folder_path(generation_id)
        sparse_dir = os.path.join(folder, "colmap", "sparse")
        if not os.path.exists(sparse_dir):
            raise ValueError(
                f"COLMAP sparse directory not found for generation {generation_id}"
            )

        frames_dir = os.path.join(folder, "images")
        frames_count = (
            len(
                [
                    f
                    for f in os.listdir(frames_dir)
                    if os.path.isfile(os.path.join(frames_dir, f))
                ]
            )
            if os.path.exists(frames_dir)
            else None
        )

        return evaluate_sparse_reconstructions(
            sparse_dir=sparse_dir, total_input_frames=frames_count
        )

    def _make_generation_folder_path(self, generation_id: str) -> str:
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        return os.path.join(backend_root, f"data/splats/{generation_id}")

    def _save_status(self, generation_id: str, data: dict) -> bool:
        file = os.path.join(
            self._make_generation_folder_path(generation_id), "status.json"
        )

        try:
            with open(file, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except:
            return False


def _run_generation(inputs: GenerationInputs, job_name: str) -> GenerationRun:
    pipeline = SplatPipeline(job_name=job_name, inputs=inputs)
    return pipeline.run()


def _run_restart_brush(inputs: RestartBrushInputs, job_name: str) -> GenerationRun:
    pipeline = RestartBrushPipeline(job_name=job_name, inputs=inputs)
    return pipeline.run()
