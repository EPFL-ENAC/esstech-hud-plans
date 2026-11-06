import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from starlette.concurrency import run_in_threadpool

from api.lib.workflows import splat_generation as workflow
from api.models.reconstruction import ReconstructionArtifactUpdate
from api.models.workflows import (
    FramePickerSettings,
    SpirulaGeometrySettings,
    SpirulaSfmSettings,
    SpirulaTrainSettings,
    SplatGenerationWorkflowSettings,
)


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
            return "recorded"

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
                (4, 0.1),  # Regressing output (e.g. another reconstruction).
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

    async def record(received_id, *, progress, artifact_changes):
        attempts.append(progress)
        if len(attempts) == 1:
            if deleted:
                raise workflow.ReconstructionNotFoundError()
            raise OSError("Database temporarily unavailable")

    @asynccontextmanager
    async def service():
        yield SimpleNamespace(record_progress=record)

    monkeypatch.setattr(workflow, "_reconstruction_service", service)
    report = workflow._progress_callback(uuid4(), 0.4, 0.6)
    assert report is not None

    def compute() -> None:
        report(0.5)
        clock.now = 1
        report(0.5)
        clock.now = 2
        report(0.5)
        clock.now = 4
        report(0.5)  # A successful retry must not publish the same value again.

    asyncio.run(run_in_threadpool(compute))
    assert attempts == pytest.approx([0.5] if deleted else [0.5, 0.5])


def test_progress_without_reconstruction_does_not_need_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_service():
        pytest.fail("Progress without a reconstruction must not open a session")

    monkeypatch.setattr(workflow, "_reconstruction_service", unexpected_service)
    assert workflow._progress_callback(None, 0.4, 0.6) is None
    assert (
        asyncio.run(workflow._record_reconstruction_progress(None, progress=0.5))
        == "disabled"
    )


@pytest.mark.parametrize("failure_stage", ["entry", "write", "cleanup"])
@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("Connection refused"),
        OperationalError("UPDATE", {}, RuntimeError("Database unavailable")),
        RuntimeError("Unexpected publishing error"),
    ],
)
def test_progress_publishing_failures_are_logged_and_non_fatal(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_stage: str,
    error: Exception,
) -> None:
    reconstruction_id = uuid4()

    async def record(*args, **kwargs):
        if failure_stage == "write":
            raise error

    @asynccontextmanager
    async def service():
        if failure_stage == "entry":
            raise error
        try:
            yield SimpleNamespace(record_progress=record)
        finally:
            if failure_stage == "cleanup":
                raise error

    monkeypatch.setattr(workflow, "_reconstruction_service", service)
    with caplog.at_level(logging.WARNING, logger=workflow.__name__):
        outcome = asyncio.run(
            workflow._record_reconstruction_progress(reconstruction_id, progress=0.25)
        )

    assert outcome == "failed"
    warning = caplog.records[-1]
    assert str(reconstruction_id) in warning.getMessage()
    assert "0.25" in warning.getMessage()
    assert warning.exc_info is not None
    assert warning.exc_info[1] is error


def test_progress_persists_artifacts_and_closes_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reconstruction_id = uuid4()
    artifacts = ReconstructionArtifactUpdate(frames_directory="/data/frames")
    closed = False

    async def record(received_id, *, progress, artifact_changes):
        assert received_id == reconstruction_id
        assert progress == 0.25
        assert artifact_changes == artifacts

    @asynccontextmanager
    async def service():
        nonlocal closed
        try:
            yield SimpleNamespace(record_progress=record)
        finally:
            closed = True

    monkeypatch.setattr(workflow, "_reconstruction_service", service)
    assert (
        asyncio.run(
            workflow._record_reconstruction_progress(
                reconstruction_id,
                progress=0.25,
                artifacts=artifacts,
            )
        )
        == "recorded"
    )
    assert closed


@pytest.mark.parametrize("error_type", [asyncio.CancelledError, KeyboardInterrupt])
def test_progress_does_not_swallow_control_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[BaseException],
) -> None:
    async def record(*args, **kwargs):
        raise error_type()

    @asynccontextmanager
    async def service():
        yield SimpleNamespace(record_progress=record)

    monkeypatch.setattr(workflow, "_reconstruction_service", service)
    with pytest.raises(error_type):
        asyncio.run(workflow._record_reconstruction_progress(uuid4(), progress=0.25))


def test_progress_callback_survives_thread_bridge_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def unavailable_bridge(*args):
        raise RuntimeError("Thread bridge unavailable")

    monkeypatch.setattr(
        workflow, "from_thread", SimpleNamespace(run=unavailable_bridge)
    )
    report = workflow._progress_callback(uuid4(), 0.4, 0.6)
    assert report is not None
    report(0.5)
    assert "Could not publish progress" in caplog.text


@pytest.mark.parametrize(
    "task",
    [
        workflow.extract_frames_task,
        workflow.pick_frames_task,
        workflow.reconstruct_with_spirula_task,
        workflow.predict_geometry_maps_task,
        workflow.train_with_spirula_task,
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


@pytest.mark.parametrize(
    "task",
    [
        workflow.extract_frames_task,
        workflow.reconstruct_with_spirula_task,
        workflow.train_with_spirula_task,
    ],
)
def test_task_cache_key_excludes_process_ownership(task) -> None:
    context = SimpleNamespace(task=task, task_run=SimpleNamespace(flow_run_id=uuid4()))
    inputs = {
        "execution_environment": workflow.LocalCommandExecutionEnvironment(),
        "input": 1,
    }
    key = task.cache_policy.compute_key(context, inputs, {})
    assert key is not None
    inputs["execution_environment"] = workflow.LocalCommandExecutionEnvironment()
    assert key == task.cache_policy.compute_key(context, inputs, {})
    inputs["input"] = 2
    assert key != task.cache_policy.compute_key(context, inputs, {})


@pytest.mark.parametrize(
    "tool", ["ffmpeg", "spirula-sfm", "spirula-train", "frame-picker"]
)
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
        return "recorded"

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
                "spirula-sfm": ["1/42   frame_00001.jpg   Features: 823"],
                "spirula-train": ["Loading config", "step  15000/30000  ( 50%)"],
            }[tool]
            for record in records:
                kwargs["on_log"](record)
        assert updates == pytest.approx([0.25 / 42 if tool == "spirula-sfm" else 0.5])
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
                execution_environment=workflow.LocalCommandExecutionEnvironment(),
                report_progress=report,
            )
        )
    elif tool == "spirula-sfm":
        monkeypatch.setattr(workflow, "run_spirula_sfm", compute)
        asyncio.run(
            workflow.reconstruct_with_spirula_task.fn(
                str(tmp_path),
                "frames",
                "colmap",
                SpirulaSfmSettings(),
                execution_environment=workflow.LocalCommandExecutionEnvironment(),
                report_progress=report,
            )
        )
    elif tool == "spirula-train":
        monkeypatch.setattr(workflow, "run_spirula_train", compute)
        asyncio.run(
            workflow.train_with_spirula_task.fn(
                str(tmp_path),
                "dataset",
                "splat.ply",
                SpirulaTrainSettings(),
                execution_environment=workflow.LocalCommandExecutionEnvironment(),
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


@pytest.mark.parametrize("use_geometry", [False, True])
@pytest.mark.parametrize("use_frame_picker", [False, True])
@pytest.mark.parametrize("train_error", [None, RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("failed_progress", [None, 0.25, 0.4, 0.7, 0.92, 0.95, "all"])
def test_flow_combines_intermediate_updates_with_validated_milestones(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    use_frame_picker: bool,
    use_geometry: bool,
    train_error: type[BaseException] | None,
    failed_progress: float | str | None,
) -> None:
    updates: list[tuple[float, object]] = []
    monkeypatch.setattr(
        workflow, "get_run_logger", lambda: SimpleNamespace(info=lambda *args: None)
    )

    async def record(received_id, *, progress, artifact_changes):
        updates.append((progress, artifact_changes))
        if failed_progress == "all" or progress == failed_progress:
            raise ConnectionRefusedError("Connection refused")

    @asynccontextmanager
    async def service():
        yield SimpleNamespace(record_progress=record)

    async def fake_task(**kwargs):
        await run_in_threadpool(kwargs["report_progress"], 0.5)
        return kwargs.get("colmap_directory", kwargs["frames_directory"])

    async def fake_train(**kwargs):
        await run_in_threadpool(kwargs["report_progress"], 0.5)
        if train_error is not None:
            raise train_error("spirula train failed to export")
        return kwargs["splat_path"]

    async def fake_geometry(**kwargs):
        return kwargs["dataset_directory"]

    async def fake_point_cloud(**kwargs):
        assert train_error is None
        assert kwargs == {
            "splat_path": str(tmp_path / "splat.ply"),
            "colmap_directory": str(tmp_path / "colmap"),
        }

    monkeypatch.setattr(workflow, "_reconstruction_service", service)
    monkeypatch.setattr(workflow, "extract_frames_task", fake_task)
    monkeypatch.setattr(workflow, "pick_frames_task", fake_task)
    monkeypatch.setattr(workflow, "reconstruct_with_spirula_task", fake_task)
    monkeypatch.setattr(workflow, "predict_geometry_maps_task", fake_geometry)
    monkeypatch.setattr(workflow, "train_with_spirula_task", fake_train)
    monkeypatch.setattr(workflow, "generate_plan_point_cloud_task", fake_point_cloud)

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
                frame_picker=FramePickerSettings() if use_frame_picker else None,
                spirula_geometry=SpirulaGeometrySettings(compute_depth=use_geometry),
            ),
            owner_id=uuid4(),
            reconstruction_id=uuid4(),
        )

    if train_error is not None:
        with pytest.raises(train_error, match="failed to export"):
            asyncio.run(run())
    else:
        assert asyncio.run(run()) == str(tmp_path / "splat.ply")

    expected = [0.15, 0.25]
    if use_frame_picker:
        expected.append(0.325)
    expected.append(0.4)
    if use_geometry:
        expected.extend([0.525, 0.65, 0.7])
    else:
        expected.extend([0.55, 0.7])
    expected.append(0.81)
    if train_error is None:
        expected.extend([0.92, 0.95])
    assert [progress for progress, _ in updates] == pytest.approx(expected)
    assert [progress for progress, artifacts in updates if artifacts is not None] == (
        [0.25, 0.4, 0.7] if train_error is not None else [0.25, 0.4, 0.7, 0.92, 0.95]
    )
