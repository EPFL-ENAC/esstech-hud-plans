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
        if run is None:
            return None

        if run.status != "completed":
            return None

        return run

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
                "steps_list": ["ffmpeg", "colmap", "brush", "blueprint_extraction"],
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
                "steps_list": ["ffmpeg", "colmap", "brush", "blueprint_extraction"],
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
                "steps_list": ["ffmpeg", "colmap", "brush", "blueprint_extraction"],
                "steps": {},
            }

    def get_blueprints(self, generation_id: str) -> dict:
        backend_root = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", ".."
        )
        blueprint_prefix = os.path.join(
            backend_root, f"data/splats/{generation_id}/blueprint"
        )

        views = {
            "top": f"{blueprint_prefix}_top.png",
            "bottom": f"{blueprint_prefix}_bottom.png",
            "front": f"{blueprint_prefix}_front.png",
            "back": f"{blueprint_prefix}_back.png",
            "left": f"{blueprint_prefix}_left.png",
            "right": f"{blueprint_prefix}_right.png",
        }

        for key, path in views.items():
            if not os.path.exists(path):
                views[key] = None

        return views


def _run_generation(inputs: GenerationInputs, job_name: str) -> GenerationRun:
    pipeline = SplatPipeline(job_name=job_name, inputs=inputs)
    return pipeline.run()
