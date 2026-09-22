import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api.lib.workflows import splat_generation as workflow
from api.models.workflows import (
    BrushSettings,
    ColmapSettings,
    FramePickerSettings,
    SplatGenerationWorkflowSettings,
)
from starlette.concurrency import run_in_threadpool


def test_progress_callback_scales_throttles_and_writes_on_flow_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconstruction_id = uuid4()
    updates: list[float] = []
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(workflow, "time", SimpleNamespace(monotonic=lambda: clock.now))

    async def run() -> None:
        loop = asyncio.get_running_loop()
        flow_thread = threading.get_ident()

        async def record(received_id, *, progress):
            assert received_id == reconstruction_id
            assert asyncio.get_running_loop() is loop
            assert threading.get_ident() == flow_thread
            updates.append(progress)

        monkeypatch.setattr(workflow, "_record_reconstruction_progress", record)
        report = workflow._progress_callback(reconstruction_id, 0.4, 0.6)
        assert report is not None

        def compute() -> None:
            assert threading.get_ident() != flow_thread
            for now, progress in [
                (0, 0),
                (0, 0.25),
                (1, 0.5),  # Throttled.
                (2, 0.5),
                (4, 0.1),  # Regressing output (e.g. another COLMAP model).
                (4, float("nan")),
                (4, float("inf")),
                (4, -1),
                (6, 1),  # Reserve the endpoint for successful completion.
                (8, 0.8),
                (8, 2),  # Same capped value.
            ]:
                clock.now = now
                report(progress)

        await run_in_threadpool(compute)

    asyncio.run(run())
    assert updates == pytest.approx([0.45, 0.50, 0.598])


@pytest.mark.parametrize("deleted", [False, True])
def test_progress_write_errors_do_not_interrupt_compute(
    monkeypatch: pytest.MonkeyPatch, deleted: bool
) -> None:
    attempts: list[float] = []
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(workflow, "time", SimpleNamespace(monotonic=lambda: clock.now))

    async def record(received_id, *, progress):
        attempts.append(progress)
        if len(attempts) == 1:
            if deleted:
                raise workflow.ReconstructionNotFoundError()
            raise OSError("Database temporarily unavailable")

    monkeypatch.setattr(workflow, "_record_reconstruction_progress", record)
    report = workflow._progress_callback(uuid4(), 0.4, 0.6)
    assert report is not None

    def compute() -> None:
        report(0.5)
        clock.now = 1
        report(0.5)
        clock.now = 2
        report(0.5)

    asyncio.run(run_in_threadpool(compute))
    assert attempts == pytest.approx([0.5] if deleted else [0.5, 0.5])


def test_progress_without_reconstruction_does_not_need_database() -> None:
    assert workflow._progress_callback(None, 0.4, 0.6) is None


@pytest.mark.parametrize(
    "task",
    [
        workflow.extract_frames_task,
        workflow.pick_frames_task,
        workflow.reconstruct_with_colmap_task,
        workflow.train_with_brush_task,
    ],
)
def test_task_cache_key_excludes_unserializable_progress_callback(task) -> None:
    lock = threading.Lock()

    def report(progress: float) -> None:
        with lock:
            pass

    context = SimpleNamespace(task=task, task_run=SimpleNamespace(flow_run_id=uuid4()))
    policy = task.cache_policy
    key = policy.compute_key(context, {"report_progress": report, "input": 1}, {})
    assert key is not None
    assert key == policy.compute_key(context, {"report_progress": None, "input": 1}, {})
    assert key != policy.compute_key(context, {"report_progress": None, "input": 2}, {})


@pytest.mark.parametrize("tool", ["ffmpeg", "colmap", "brush", "frame-picker"])
def test_task_reports_progress_before_compute_returns(
    monkeypatch: pytest.MonkeyPatch, tmp_path, tool: str
) -> None:
    updates: list[float] = []
    flow_thread = threading.get_ident()

    def get_run_logger():
        # Task setup runs on the event loop; only compute is offloaded.
        assert threading.get_ident() == flow_thread
        asyncio.get_running_loop()
        return SimpleNamespace(info=lambda *args: None)

    async def record(received_id, *, progress):
        assert threading.get_ident() == flow_thread
        updates.append(progress)

    monkeypatch.setattr(workflow, "get_run_logger", get_run_logger)
    monkeypatch.setattr(workflow, "_record_reconstruction_progress", record)
    report = workflow._progress_callback(uuid4(), 0.0, 1.0)

    def compute(*args, **kwargs):
        assert threading.get_ident() != flow_thread
        if tool == "frame-picker":
            kwargs["on_progress"]("Analyzing frames", 0.5)
        else:
            records = {
                "ffmpeg": ["Duration: 00:00:10.00", "time=00:00:05.00"],
                "colmap": ["Processed file [50/100]"],
                "brush": ["Completed loading", "500/1000 Steps"],
            }[tool]
            for record in records:
                kwargs["on_log"](record)
        assert updates == pytest.approx([0.15 if tool == "colmap" else 0.5])
        return [object()] if tool == "frame-picker" else tmp_path

    if tool == "ffmpeg":
        monkeypatch.setattr(workflow, "run_frame_extraction", compute)
        asyncio.run(
            workflow.extract_frames_task.fn(
                str(tmp_path),
                "video",
                "frames",
                2,
                1920,
                1080,
                report_progress=report,
            )
        )
    elif tool == "colmap":
        monkeypatch.setattr(workflow, "run_colmap_reconstruction", compute)
        asyncio.run(
            workflow.reconstruct_with_colmap_task.fn(
                str(tmp_path),
                "frames",
                "colmap",
                ColmapSettings(),
                report_progress=report,
            )
        )
    elif tool == "brush":
        monkeypatch.setattr(workflow, "run_brush_training", compute)
        asyncio.run(
            workflow.train_with_brush_task.fn(
                str(tmp_path),
                "dataset",
                "splat.ply",
                BrushSettings(),
                report_progress=report,
            )
        )
    else:
        monkeypatch.setattr(workflow, "pick_frames", compute)
        asyncio.run(
            workflow.pick_frames_task.fn(
                str(tmp_path),
                "video",
                "raw",
                "frames",
                FramePickerSettings(),
                report_progress=report,
            )
        )


@pytest.mark.parametrize("use_frame_picker", [False, True])
@pytest.mark.parametrize("fail_brush", [False, True])
def test_flow_combines_intermediate_updates_with_validated_milestones(
    monkeypatch: pytest.MonkeyPatch, tmp_path, use_frame_picker: bool, fail_brush: bool
) -> None:
    updates: list[tuple[float, object]] = []
    monkeypatch.setattr(
        workflow, "get_run_logger", lambda: SimpleNamespace(info=lambda *args: None)
    )

    async def record(received_id, *, progress, artifacts=None):
        updates.append((progress, artifacts))

    async def fake_task(**kwargs):
        await run_in_threadpool(kwargs["report_progress"], 0.5)
        return kwargs.get("colmap_directory", kwargs["frames_directory"])

    async def fake_brush(**kwargs):
        await run_in_threadpool(kwargs["report_progress"], 0.5)
        if fail_brush:
            raise RuntimeError("Brush failed to export")
        return kwargs["splat_path"]

    monkeypatch.setattr(workflow, "_record_reconstruction_progress", record)
    monkeypatch.setattr(workflow, "extract_frames_task", fake_task)
    monkeypatch.setattr(workflow, "pick_frames_task", fake_task)
    monkeypatch.setattr(workflow, "reconstruct_with_colmap_task", fake_task)
    monkeypatch.setattr(workflow, "train_with_brush_task", fake_brush)

    async def run():
        return await workflow.splat_generation_flow.fn(
            artifact_id=uuid4(),
            workspace_directory=str(tmp_path),
            video_path=str(tmp_path / "input.mp4"),
            raw_frames_directory=str(tmp_path / "raw"),
            frames_directory=str(tmp_path / "frames"),
            colmap_directory=str(tmp_path / "colmap"),
            splat_path=str(tmp_path / "splat.ply"),
            settings=SplatGenerationWorkflowSettings(
                frame_picker=FramePickerSettings() if use_frame_picker else None
            ),
            owner_id=uuid4(),
            reconstruction_id=uuid4(),
        )

    if fail_brush:
        with pytest.raises(RuntimeError, match="failed to export"):
            asyncio.run(run())
    else:
        assert asyncio.run(run()) == str(tmp_path / "splat.ply")

    expected = [0.15, 0.25]
    if use_frame_picker:
        expected.append(0.325)
    expected.extend([0.4, 0.55, 0.7, 0.825])
    if not fail_brush:
        expected.append(0.95)
    assert [progress for progress, _ in updates] == pytest.approx(expected)
    assert [progress for progress, artifacts in updates if artifacts is not None] == (
        [0.25, 0.4, 0.7] if fail_brush else [0.25, 0.4, 0.7, 0.95]
    )
