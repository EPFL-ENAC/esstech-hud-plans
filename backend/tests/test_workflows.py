import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from api.lib.workflows import __main__ as workflow_runner
from api.lib.workflows import common as workflow_common
from api.lib.workflows import counter as counter_workflow
from api.lib.workflows import frame_extraction as frame_workflow
from api.models.auth import User
from api.models.workflows import (
    ColmapSettings,
    FfmpegSettings,
    FrameExtractionWorkflowSettings,
)
from api.services.auth import require_user
from api.views import workflows as workflow_views
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prefect.client.schemas.objects import Log, StateType


@pytest.fixture
def workflow_data_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "workflow data"
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", directory)
    return directory


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(workflow_views.router, prefix="/workflows")
    app.dependency_overrides[require_user] = lambda: User(sub="owner-1")
    return TestClient(app)


def _flow_run(
    state_type: StateType,
    *,
    owner_id: str = "owner-1",
    artifact_id: UUID | None = None,
    message: str | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        state_type=state_type,
        state=SimpleNamespace(message=message),
        parameters={
            "owner_id": owner_id,
            "artifact_id": str(artifact_id or uuid4()),
        },
    )


def _log(message: str, *, timestamp: datetime | None = None) -> Log:
    return Log(
        name="prefect.task_runs",
        level=20,
        message=message,
        timestamp=timestamp or datetime.now(UTC),
        flow_run_id=uuid4(),
        task_run_id=uuid4(),
    )


def test_frame_extraction_artifact_owns_its_paths_and_lifecycle(
    workflow_data_directory: Path,
) -> None:
    artifact = frame_workflow.FrameExtractionArtifact.create(workflow_data_directory)

    assert artifact.video_path.name == "input.mp4"
    assert artifact.root_directory.parent == workflow_data_directory
    assert artifact.video_path.parent == artifact.root_directory / "video"
    assert artifact.frames_directory == artifact.root_directory / "frames"
    assert artifact.colmap_directory == artifact.root_directory / "colmap"
    assert artifact.colmap_sparse_directory == (
        artifact.colmap_directory / "sparse" / "0"
    )

    loaded = frame_workflow.FrameExtractionArtifact.load(
        artifact.artifact_id, workflow_data_directory
    )
    assert loaded == artifact
    from_flow_run = frame_workflow.FrameExtractionArtifact.from_flow_run(
        _flow_run(StateType.COMPLETED, artifact_id=artifact.artifact_id),
        workflow_data_directory,
    )
    assert from_flow_run == artifact

    artifact.video_path.write_bytes(b"video")
    artifact.remove()
    assert not artifact.root_directory.exists()


def test_schedule_frame_extraction_returns_prefect_run_id(
    monkeypatch: pytest.MonkeyPatch, workflow_data_directory: Path
) -> None:
    artifact = frame_workflow.FrameExtractionArtifact.create(workflow_data_directory)
    expected_id = uuid4()
    captured: dict = {}

    async def fake_run_deployment(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=expected_id)

    monkeypatch.setattr(frame_workflow, "arun_deployment", fake_run_deployment)

    result = asyncio.run(
        frame_workflow.schedule_frame_extraction(
            artifact,
            FrameExtractionWorkflowSettings(
                ffmpeg=FfmpegSettings(
                    fps=3,
                    fit_in_width=640,
                    fit_in_height=480,
                ),
                colmap=ColmapSettings(
                    data_type="internet",
                    quality="high",
                    camera_model="RADIAL",
                    single_camera=False,
                    use_gpu=True,
                    use_global_mapper=True,
                ),
            ),
            "owner-1",
        )
    )

    assert result == expected_id
    assert captured["name"] == "frame-extraction/default"
    assert captured["timeout"] == 0
    assert captured["as_subflow"] is False
    assert captured["parameters"] == {
        "artifact_id": str(artifact.artifact_id),
        "workspace_directory": str(artifact.root_directory.resolve()),
        "video_path": str(artifact.video_path.resolve()),
        "frames_directory": str(artifact.frames_directory.resolve()),
        "colmap_directory": str(artifact.colmap_directory.resolve()),
        "settings": {
            "ffmpeg": {
                "fps": 3.0,
                "fit_in_width": 640,
                "fit_in_height": 480,
            },
            "colmap": {
                "data_type": "internet",
                "quality": "high",
                "camera_model": "RADIAL",
                "single_camera": False,
                "use_gpu": True,
                "use_global_mapper": True,
            },
        },
        "owner_id": "owner-1",
    }


def test_counter_flow_logs_once_per_second_for_sixty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[int] = []
    records: list[tuple[str, int]] = []

    class FakeRunLogger:
        def info(self, message: str, count: int) -> None:
            records.append((message, count))

    monkeypatch.setattr(counter_workflow.time, "sleep", sleeps.append)
    monkeypatch.setattr(counter_workflow, "get_run_logger", lambda: FakeRunLogger())

    counter_workflow.counter_flow.fn("owner-1")

    assert sleeps == [1] * 60
    assert records == [("Counter: %d", count) for count in range(1, 61)]


def test_schedule_counter_returns_prefect_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_id = uuid4()
    captured: dict = {}

    async def fake_run_deployment(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=expected_id)

    monkeypatch.setattr(counter_workflow, "arun_deployment", fake_run_deployment)

    result = asyncio.run(counter_workflow.schedule_counter("owner-1"))

    assert result == expected_id
    assert captured == {
        "name": "counter/default",
        "parameters": {"owner_id": "owner-1"},
        "timeout": 0,
        "as_subflow": False,
    }


def test_workflow_runner_serves_frame_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    class FakeFlow:
        def serve(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(workflow_runner, "frame_extraction_flow", FakeFlow())

    workflow_runner.serve_workflows()

    assert captured == {"name": "default", "limit": 1}


def test_extract_frames_task_sends_ffmpeg_output_to_prefect_run_logger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    records: list[tuple[str, str]] = []

    class FakeRunLogger:
        def info(self, message: str, record: str) -> None:
            records.append((message, record))

    def fake_run_frame_extraction(*args, on_log, **kwargs):
        assert kwargs["workspace_directory"] == tmp_path
        assert (
            kwargs["execution_environment"]
            is frame_workflow.LOCAL_EXECUTION_ENVIRONMENT
        )
        on_log("frame=1")
        on_log("frame=2")
        return tmp_path / "frames"

    monkeypatch.setattr(frame_workflow, "get_run_logger", lambda: FakeRunLogger())
    monkeypatch.setattr(
        frame_workflow, "run_frame_extraction", fake_run_frame_extraction
    )

    result = frame_workflow.extract_frames_task.fn(
        str(tmp_path),
        "input",
        str(tmp_path / "frames"),
        2,
        100,
        100,
    )

    assert result == str(tmp_path / "frames")
    assert records == [
        ("ffmpeg: %s", "frame=1"),
        ("ffmpeg: %s", "frame=2"),
    ]


def test_reconstruct_with_colmap_task_sends_output_to_prefect_run_logger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    records: list[tuple[str, str]] = []
    settings = ColmapSettings()

    class FakeRunLogger:
        def info(self, message: str, record: str) -> None:
            records.append((message, record))

    def fake_run_colmap_reconstruction(*args, on_log, **kwargs):
        assert kwargs["workspace_directory"] == tmp_path
        assert (
            kwargs["execution_environment"]
            is frame_workflow.LOCAL_EXECUTION_ENVIRONMENT
        )
        on_log("feature extraction")
        on_log("mapping")
        return tmp_path / "colmap"

    monkeypatch.setattr(frame_workflow, "get_run_logger", lambda: FakeRunLogger())
    monkeypatch.setattr(
        frame_workflow,
        "run_colmap_reconstruction",
        fake_run_colmap_reconstruction,
    )

    result = frame_workflow.reconstruct_with_colmap_task.fn(
        str(tmp_path),
        str(tmp_path / "frames"),
        str(tmp_path / "colmap"),
        settings,
    )

    assert result == str(tmp_path / "colmap")
    assert records == [
        ("colmap: %s", "feature extraction"),
        ("colmap: %s", "mapping"),
    ]


@pytest.mark.parametrize("use_scitas", [False, True])
def test_frame_extraction_flow_selects_colmap_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, use_scitas: bool
) -> None:
    calls: list[tuple] = []
    settings = FrameExtractionWorkflowSettings()

    class FakeRunLogger:
        def info(self, *args) -> None:
            pass

    def fake_extract_frames_task(**kwargs):
        calls.append(("ffmpeg", kwargs))
        return str(tmp_path / "frames")

    def fake_colmap_task(**kwargs):
        calls.append(("colmap", kwargs))
        return str(tmp_path / "colmap")

    monkeypatch.setattr(frame_workflow, "get_run_logger", lambda: FakeRunLogger())
    monkeypatch.setattr(frame_workflow.config, "USE_SCITAS", use_scitas)
    monkeypatch.setattr(frame_workflow, "extract_frames_task", fake_extract_frames_task)
    monkeypatch.setattr(
        frame_workflow,
        "reconstruct_with_colmap_task",
        fake_colmap_task,
    )

    result = frame_workflow.frame_extraction_flow.fn(
        artifact_id=uuid4(),
        workspace_directory=str(tmp_path),
        video_path="input.mov",
        frames_directory=str(tmp_path / "frames"),
        colmap_directory=str(tmp_path / "colmap"),
        settings=settings,
        owner_id="owner-1",
    )

    assert result == str(tmp_path / "colmap")
    colmap_environment = (
        frame_workflow.SCITAS_EXECUTION_ENVIRONMENT
        if use_scitas
        else frame_workflow.LOCAL_EXECUTION_ENVIRONMENT
    )
    assert calls == [
        (
            "ffmpeg",
            {
                "workspace_directory": str(tmp_path),
                "video_path": "input.mov",
                "frames_directory": str(tmp_path / "frames"),
                "fps": 2.0,
                "fit_in_width": 1920,
                "fit_in_height": 1920,
                "execution_environment": frame_workflow.LOCAL_EXECUTION_ENVIRONMENT,
            },
        ),
        (
            "colmap",
            {
                "workspace_directory": str(tmp_path),
                "frames_directory": str(tmp_path / "frames"),
                "colmap_directory": str(tmp_path / "colmap"),
                "settings": settings.colmap,
                "execution_environment": colmap_environment,
            },
        ),
    ]


def test_submit_counter_returns_202(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    workflow_id = uuid4()

    async def fake_schedule(owner_id: str):
        assert owner_id == "owner-1"
        return workflow_id

    monkeypatch.setattr(workflow_views, "schedule_counter", fake_schedule)

    response = client.post("/workflows/counter")

    assert response.status_code == 202
    assert response.json() == {"workflow_id": str(workflow_id)}


def test_submit_frame_extraction_stores_upload_and_returns_202(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    workflow_id = uuid4()

    async def fake_schedule(*, artifact, settings, owner_id):
        assert artifact.video_path.read_bytes() == b"video bytes"
        assert artifact.video_path.name == "input.mp4"
        assert settings == FrameExtractionWorkflowSettings()
        assert owner_id == "owner-1"
        return workflow_id

    monkeypatch.setattr(workflow_views, "schedule_frame_extraction", fake_schedule)

    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("../../unsafe name.MP4", b"video bytes", "video/mp4")},
        data={"settings": "{}"},
    )

    assert response.status_code == 202
    assert response.json() == {"workflow_id": str(workflow_id)}


def test_submit_frame_extraction_validates_nested_tool_settings(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    workflow_id = uuid4()

    async def fake_schedule(*, artifact, settings, owner_id):
        assert settings == FrameExtractionWorkflowSettings(
            ffmpeg=FfmpegSettings(
                fps=4,
                fit_in_width=1280,
                fit_in_height=720,
            ),
            colmap=ColmapSettings(
                data_type="individual",
                quality="medium",
                camera_model="PINHOLE",
                single_camera=False,
                use_gpu=True,
                use_global_mapper=True,
            ),
        )
        return workflow_id

    monkeypatch.setattr(workflow_views, "schedule_frame_extraction", fake_schedule)
    settings = {
        "ffmpeg": {
            "fps": 4,
            "fit_in_width": 1280,
            "fit_in_height": 720,
        },
        "colmap": {
            "data_type": "individual",
            "quality": "medium",
            "camera_model": "PINHOLE",
            "single_camera": False,
            "use_gpu": True,
            "use_global_mapper": True,
        },
    }

    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("input.mp4", b"video bytes", "video/mp4")},
        data={"settings": json.dumps(settings)},
    )

    assert response.status_code == 202


@pytest.mark.parametrize("settings", ["not-json", '{"ffmpeg":{"fps":0}}'])
def test_submit_frame_extraction_rejects_invalid_nested_settings(
    settings: str,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("input.mp4", b"video bytes", "video/mp4")},
        data={"settings": settings},
    )

    assert response.status_code == 422
    assert not workflow_data_directory.exists()


def test_submit_frame_extraction_requires_settings(
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("input.mp4", b"video bytes", "video/mp4")},
    )

    assert response.status_code == 422
    assert not workflow_data_directory.exists()


def test_submit_frame_extraction_cleans_up_after_scheduling_failure(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    async def fake_schedule(**kwargs):
        raise ConnectionError("Prefect is offline")

    monkeypatch.setattr(workflow_views, "schedule_frame_extraction", fake_schedule)

    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("input.mp4", b"video bytes", "video/mp4")},
        data={"settings": "{}"},
    )

    assert response.status_code == 503
    assert list(workflow_data_directory.iterdir()) == []


def test_submit_frame_extraction_rejects_non_video(
    workflow_data_directory: Path, client: TestClient
) -> None:
    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("input.txt", b"not a video", "text/plain")},
        data={"settings": "{}"},
    )

    assert response.status_code == 400
    assert not workflow_data_directory.exists()


@pytest.mark.parametrize("state_type", list(StateType))
def test_workflow_status_maps_prefect_states(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    state_type: StateType,
) -> None:
    workflow_id = uuid4()

    async def fake_get_owned_workflow_run(*, workflow_id: UUID, owner_id: str):
        assert owner_id == "owner-1"
        flow_run = _flow_run(state_type, message="A status message")
        flow_run.id = workflow_id
        return flow_run

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/status/{workflow_id}")

    assert response.status_code == 200
    assert response.json() == {
        "workflow_id": str(workflow_id),
        "status": state_type.value.lower(),
        "message": "A status message",
    }


def test_workflow_status_hides_unknown_or_unowned_runs(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    async def fake_get_owned_workflow_run(*args, **kwargs):
        raise workflow_common.WorkflowNotFoundError

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/status/{uuid4()}")

    assert response.status_code == 404


def test_workflow_status_returns_503_when_prefect_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    async def fake_get_owned_workflow_run(*args, **kwargs):
        raise ConnectionError("Prefect is unavailable")

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/status/{uuid4()}")

    assert response.status_code == 503
    assert response.json() == {"detail": "Workflow service is unavailable"}


def test_workflow_result_returns_completed_artifact_directories(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    workflow_id = uuid4()
    artifact = frame_workflow.FrameExtractionArtifact.create(workflow_data_directory)
    artifact.frames_directory.mkdir(parents=True)
    artifact.colmap_sparse_directory.mkdir(parents=True)

    async def fake_get_owned_workflow_run(*args, **kwargs):
        return _flow_run(StateType.COMPLETED, artifact_id=artifact.artifact_id)

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/result/{workflow_id}")

    assert response.status_code == 200
    assert response.json() == {
        "frames_directory": str(artifact.frames_directory.resolve()),
        "colmap_directory": str(artifact.colmap_directory.resolve()),
    }


def test_workflow_result_rejects_missing_colmap_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    artifact = frame_workflow.FrameExtractionArtifact.create(workflow_data_directory)
    artifact.frames_directory.mkdir(parents=True)

    async def fake_get_owned_workflow_run(*args, **kwargs):
        return _flow_run(StateType.COMPLETED, artifact_id=artifact.artifact_id)

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/result/{uuid4()}")

    assert response.status_code == 500
    assert "COLMAP sparse reconstruction" in response.json()["detail"]


def test_workflow_result_returns_409_until_completed(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    async def fake_get_owned_workflow_run(*args, **kwargs):
        return _flow_run(StateType.RUNNING)

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/result/{uuid4()}")

    assert response.status_code == 409


def test_workflow_result_rejects_missing_directory(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    artifact_id = uuid4()

    async def fake_get_owned_workflow_run(*args, **kwargs):
        return _flow_run(StateType.COMPLETED, artifact_id=artifact_id)

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/result/{uuid4()}")

    assert response.status_code == 500


def test_workflow_result_rejects_invalid_artifact_id(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    async def fake_get_owned_workflow_run(*args, **kwargs):
        flow_run = _flow_run(StateType.COMPLETED)
        flow_run.parameters["artifact_id"] = "not-a-uuid"
        return flow_run

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/result/{uuid4()}")

    assert response.status_code == 500


class _FakePrefectClientContext:
    def __init__(self, flow_run):
        self.flow_run = flow_run

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def read_flow_run(self, workflow_id: UUID):
        return self.flow_run


def test_get_owned_workflow_run_rejects_another_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_run = _flow_run(StateType.RUNNING, owner_id="owner-2")
    monkeypatch.setattr(
        workflow_common, "get_client", lambda: _FakePrefectClientContext(flow_run)
    )

    with pytest.raises(workflow_common.WorkflowNotFoundError):
        asyncio.run(workflow_common.get_owned_workflow_run(uuid4(), "owner-1"))


class _FakeLogsClientContext:
    def __init__(self, logs: list[Log]):
        self.logs = logs
        self.read_logs_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def read_logs(self, **kwargs):
        self.read_logs_calls.append(kwargs)
        offset = kwargs["offset"]
        limit = kwargs["limit"]
        return self.logs[offset : offset + limit]


def test_workflow_logs_snapshot_factory_is_typed_bounded_and_paginated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_run = _flow_run(StateType.RUNNING)
    base_time = datetime.now(UTC) - timedelta(seconds=10)
    expected_logs = [
        _log("first", timestamp=base_time),
        _log("second", timestamp=base_time + timedelta(seconds=1)),
        _log("third", timestamp=base_time + timedelta(seconds=2)),
    ]
    fake_client = _FakeLogsClientContext(expected_logs)
    monkeypatch.setattr(workflow_common, "LOG_PAGE_SIZE", 2)
    monkeypatch.setattr(workflow_common, "get_client", lambda: fake_client)

    snapshot = asyncio.run(
        workflow_common.WorkflowLogsSnapshot.make_snapshot_for_flow_run(flow_run)
    )

    assert isinstance(snapshot, workflow_common.WorkflowLogsSnapshot)
    assert snapshot.flow_run_id == flow_run.id
    assert snapshot.logs == tuple(expected_logs)
    assert snapshot.captured_at.tzinfo is not None
    assert [call["offset"] for call in fake_client.read_logs_calls] == [0, 2]
    for call in fake_client.read_logs_calls:
        assert call["limit"] == 2
        assert call["sort"].value == "TIMESTAMP_ASC"
        assert call["log_filter"].flow_run_id.any_ == [flow_run.id]
        assert call["log_filter"].timestamp.before_ == snapshot.captured_at


def test_stream_workflow_logs_yields_one_snapshot_then_individual_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_run = _flow_run(StateType.RUNNING)
    snapshot_log = _log("snapshot")
    live_log = _log("live")
    reconciled_log = _log("reconciled")
    now = datetime.now(UTC)
    initial_snapshot = workflow_common.WorkflowLogsSnapshot(
        flow_run.id, now, (snapshot_log,)
    )
    final_snapshot = workflow_common.WorkflowLogsSnapshot(
        flow_run.id,
        now + timedelta(seconds=1),
        (snapshot_log, live_log, reconciled_log),
    )
    snapshots = [initial_snapshot, final_snapshot]
    events: list[str] = []
    captured_arguments = None

    class FakeSubscriber:
        def __init__(self):
            self.items = iter((snapshot_log, SimpleNamespace(), live_log))

        async def __aenter__(self):
            events.append("subscription-opened")
            return self

        async def __aexit__(self, *args):
            events.append("subscription-closed")

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.items)
            except StopIteration:
                raise StopAsyncIteration from None

    def fake_flow_run_subscriber(*, flow_run_id, straggler_timeout):
        nonlocal captured_arguments
        captured_arguments = {
            "flow_run_id": flow_run_id,
            "straggler_timeout": straggler_timeout,
        }
        return FakeSubscriber()

    async def fake_snapshot(cls, requested_flow_run):
        assert requested_flow_run is flow_run
        events.append("snapshot")
        return snapshots.pop(0)

    monkeypatch.setattr(workflow_common, "FlowRunSubscriber", fake_flow_run_subscriber)
    monkeypatch.setattr(
        workflow_common.WorkflowLogsSnapshot,
        "make_snapshot_for_flow_run",
        classmethod(fake_snapshot),
    )

    async def collect_stream():
        return [item async for item in workflow_common.stream_workflow_logs(flow_run)]

    items = asyncio.run(collect_stream())

    assert items == [
        workflow_common.WorkflowLogStreamItem.from_snapshot(initial_snapshot),
        workflow_common.WorkflowLogStreamItem.from_log(live_log),
        workflow_common.WorkflowLogStreamItem.from_log(reconciled_log),
    ]
    assert [item.type for item in items] == ["snapshot", "log", "log"]
    assert captured_arguments == {
        "flow_run_id": flow_run.id,
        "straggler_timeout": workflow_common.LOG_STREAM_TERMINAL_DRAIN_SECONDS,
    }
    assert events == [
        "subscription-opened",
        "snapshot",
        "subscription-closed",
        "snapshot",
    ]


def test_stream_workflow_logs_drains_terminal_logs_then_reconciles_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_run = _flow_run(StateType.RUNNING)
    initial_log = _log("initial")
    terminal_log = _log("terminal-boundary")
    reconciled_log = _log("durable-only")
    now = datetime.now(UTC)
    initial_snapshot = workflow_common.WorkflowLogsSnapshot(
        flow_run.id, now, (initial_log,)
    )
    final_snapshot = workflow_common.WorkflowLogsSnapshot(
        flow_run.id,
        now + timedelta(seconds=4),
        (initial_log, terminal_log, reconciled_log),
    )
    snapshots = iter((initial_snapshot, final_snapshot))

    class FakeSubscriber:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            if hasattr(self, "yielded_terminal_log"):
                raise StopAsyncIteration
            self.yielded_terminal_log = True
            await asyncio.sleep(0)
            return terminal_log

    def fake_flow_run_subscriber(*, flow_run_id, straggler_timeout):
        assert flow_run_id == flow_run.id
        assert straggler_timeout == workflow_common.LOG_STREAM_TERMINAL_DRAIN_SECONDS
        return FakeSubscriber()

    async def fake_snapshot(cls, requested_flow_run):
        assert requested_flow_run is flow_run
        return next(snapshots)

    monkeypatch.setattr(workflow_common, "FlowRunSubscriber", fake_flow_run_subscriber)
    monkeypatch.setattr(
        workflow_common.WorkflowLogsSnapshot,
        "make_snapshot_for_flow_run",
        classmethod(fake_snapshot),
    )

    async def collect_stream():
        return [item async for item in workflow_common.stream_workflow_logs(flow_run)]

    items = asyncio.run(collect_stream())

    assert items == [
        workflow_common.WorkflowLogStreamItem.from_snapshot(initial_snapshot),
        workflow_common.WorkflowLogStreamItem.from_log(terminal_log),
        workflow_common.WorkflowLogStreamItem.from_log(reconciled_log),
    ]


def test_stream_workflow_logs_yields_an_empty_snapshot_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow_run = _flow_run(StateType.COMPLETED)
    snapshot = workflow_common.WorkflowLogsSnapshot(flow_run.id, datetime.now(UTC), ())

    def fake_flow_run_subscriber(*args, **kwargs):
        raise AssertionError("Terminal workflows must not open a subscription")

    async def fake_snapshot(cls, requested_flow_run):
        assert requested_flow_run is flow_run
        return snapshot

    monkeypatch.setattr(workflow_common, "FlowRunSubscriber", fake_flow_run_subscriber)
    monkeypatch.setattr(
        workflow_common.WorkflowLogsSnapshot,
        "make_snapshot_for_flow_run",
        classmethod(fake_snapshot),
    )

    async def collect_stream():
        return [item async for item in workflow_common.stream_workflow_logs(flow_run)]

    assert asyncio.run(collect_stream()) == [
        workflow_common.WorkflowLogStreamItem.from_snapshot(snapshot)
    ]


def test_listen_to_workflow_streams_snapshot_then_logs(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    flow_run = _flow_run(StateType.RUNNING)
    initial_log = _log("initial")
    live_log = _log("live")
    snapshot = workflow_common.WorkflowLogsSnapshot(
        flow_run.id,
        datetime.now(UTC),
        (initial_log,),
    )
    stream_closed = False

    async def fake_get_owned_workflow_run(*, workflow_id, owner_id):
        assert owner_id == "owner-1"
        flow_run.id = workflow_id
        return flow_run

    async def fake_stream_workflow_logs(requested_flow_run):
        nonlocal stream_closed
        assert requested_flow_run is flow_run
        try:
            yield workflow_common.WorkflowLogStreamItem.from_snapshot(snapshot)
            yield workflow_common.WorkflowLogStreamItem.from_log(live_log)
        finally:
            stream_closed = True

    monkeypatch.setattr(
        workflow_views,
        "get_owned_workflow_run",
        fake_get_owned_workflow_run,
    )
    monkeypatch.setattr(
        workflow_views,
        "stream_workflow_logs",
        fake_stream_workflow_logs,
    )

    response = client.get(f"/workflows/listen/{flow_run.id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = response.text.strip().split("\n\n")
    assert [event.splitlines()[0] for event in events] == [
        "event: snapshot",
        "event: log",
    ]
    snapshot_data = json.loads(events[0].splitlines()[1].removeprefix("data: "))
    log_data = json.loads(events[1].splitlines()[1].removeprefix("data: "))
    assert snapshot_data["flow_run_id"] == str(flow_run.id)
    assert [log["message"] for log in snapshot_data["logs"]] == ["initial"]
    assert log_data["id"] == str(live_log.id)
    assert log_data["message"] == "live"
    assert stream_closed


def test_workflow_listener_uses_workflow_id_as_its_openapi_parameter(
    client: TestClient,
) -> None:
    operation = client.get("/openapi.json").json()["paths"][
        "/workflows/listen/{workflow_id}"
    ]["get"]

    path_parameters = [
        parameter for parameter in operation["parameters"] if parameter["in"] == "path"
    ]
    assert [parameter["name"] for parameter in path_parameters] == ["workflow_id"]


def test_listen_to_workflow_hides_unknown_or_unowned_runs(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    async def fake_get_owned_workflow_run(*args, **kwargs):
        raise workflow_common.WorkflowNotFoundError

    monkeypatch.setattr(
        workflow_views,
        "get_owned_workflow_run",
        fake_get_owned_workflow_run,
    )

    response = client.get(f"/workflows/listen/{uuid4()}")

    assert response.status_code == 404


def test_listen_to_workflow_returns_503_when_stream_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
) -> None:
    flow_run = _flow_run(StateType.RUNNING)
    stream_closed = False

    async def fake_get_owned_workflow_run(*args, **kwargs):
        return flow_run

    async def failing_stream(requested_flow_run):
        nonlocal stream_closed
        try:
            raise ConnectionError("Prefect is unavailable")
            yield
        finally:
            stream_closed = True

    monkeypatch.setattr(
        workflow_views,
        "get_owned_workflow_run",
        fake_get_owned_workflow_run,
    )
    monkeypatch.setattr(
        workflow_views,
        "stream_workflow_logs",
        failing_stream,
    )

    response = client.get(f"/workflows/listen/{flow_run.id}")

    assert response.status_code == 503
    assert response.json() == {"detail": "Workflow log stream is unavailable"}
    assert stream_closed
