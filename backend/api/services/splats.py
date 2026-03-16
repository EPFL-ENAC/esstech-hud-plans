import json
import os
import sys
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass
from typing import Union

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
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        splat_dir = os.path.join(backend_root, f"data/splats/{generation_id}")
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
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        status_file = os.path.join(
            backend_root, f"data/splats/{generation_id}/status.json"
        )

        if not os.path.exists(status_file):
            return None

        try:
            with open(status_file, "r") as f:
                data = json.load(f)
            return data.get("colmap_geometric_data")
        except (json.JSONDecodeError, IOError):
            return None

    def get_settings(self, generation_id: str) -> dict | None:
        """Retrieve the settings for a generation run."""
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        status_file = os.path.join(
            backend_root, f"data/splats/{generation_id}/status.json"
        )

        if not os.path.exists(status_file):
            return None

        try:
            with open(status_file, "r") as f:
                data = json.load(f)
            return data.get("settings")
        except (json.JSONDecodeError, IOError):
            return None

    def run_restart_brush(self, inputs: RestartBrushInputs) -> GenerationRun:
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        source_dir = os.path.join(
            backend_root, f"data/splats/{inputs.colmap_generation_id}"
        )

        if not os.path.exists(source_dir):
            raise ValueError(
                f"Source generation {inputs.colmap_generation_id} not found"
            )

        new_id = uuid.uuid4().hex
        new_dir = os.path.join(backend_root, f"data/splats/{new_id}")

        os.makedirs(new_dir, exist_ok=True)

        source_status_file = os.path.join(source_dir, "status.json")
        new_status_file = os.path.join(new_dir, "status.json")

        steps_list = ["ffmpeg", "colmap", "brush"]
        if inputs.blueprint is not None:
            steps_list.append("blueprint_extraction")

        if not os.path.exists(source_status_file):
            raise ValueError(
                f"Source status file not found for generation {inputs.colmap_generation_id}"
            )

        with open(source_status_file, "r") as f:
            source_status = json.load(f)

        new_status = {
            "name": new_id,
            "overall_status": "pending",
            "progress": 0.0,
            "message": "Starting brush restart...",
            "started_at": source_status.get("started_at"),
            "finished_at": None,
            "output": None,
            "settings": {
                **source_status.get("settings", {}),
                "brush": inputs.brush.model_dump(),
                "blueprint": inputs.blueprint.model_dump()
                if inputs.blueprint
                else None,
            },
            "steps_list": steps_list,
            "steps": {},
            "colmap_geometric_data": source_status.get("colmap_geometric_data"),
        }

        source_steps = source_status.get("steps", {})
        for step in ["ffmpeg", "colmap"]:
            if step in source_steps:
                new_status["steps"][step] = source_steps[step]

        with open(new_status_file, "w") as f:
            json.dump(new_status, f, indent=2)

        run = GenerationRun(id=new_id, input_video_path="", status="pending")
        self.runs[new_id] = run

        future = self.executor.submit(
            _run_restart_brush, inputs, new_id, new_dir, source_dir
        )
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


def _run_generation(inputs: GenerationInputs, job_name: str) -> GenerationRun:
    pipeline = SplatPipeline(job_name=job_name, inputs=inputs)
    return pipeline.run()


def _run_restart_brush(
    inputs: RestartBrushInputs, job_name: str, workspace_dir: str, source_dir: str
) -> dict[str, str | list[str] | list]:
    from api.lib.restart_brush_pipeline import RestartBrushPipeline

    source_status = None
    source_status_file = os.path.join(source_dir, "status.json")
    if os.path.exists(source_status_file):
        with open(source_status_file, "r") as f:
            source_status = json.load(f)

    pipeline = RestartBrushPipeline(
        job_name=job_name,
        inputs=inputs,
        workspace_dir=workspace_dir,
        source_dir=source_dir,
        source_status=source_status,
    )
    return pipeline.run()
