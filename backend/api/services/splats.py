import os
import sys
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass

from api.data_processing.splats import generate_splats

# Add parent directory to path to import other modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class GenerationInputs:
    video_path: str


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


def _run_generation(inputs: GenerationInputs, job_name: str) -> GenerationRun:
    return generate_splats(job_name, inputs.video_path)
