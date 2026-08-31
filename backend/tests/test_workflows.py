import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from api.models.auth import User
from api.models.workflows import FrameExtractionSettings
from api.services import workflows
from api.services.auth import require_user
from api.views import workflows as workflow_views
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prefect.client.schemas.objects import StateType


@pytest.fixture
def workflow_data_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "workflow data"
    monkeypatch.setattr(workflows, "WORKFLOW_DATA_DIRECTORY", directory)
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


def test_frame_extraction_artifact_owns_its_paths_and_lifecycle(
    workflow_data_directory: Path,
) -> None:
    artifact = workflows.FrameExtractionArtifact.create(workflow_data_directory)

    assert artifact.video_path.name == "input.mp4"
    assert artifact.root_directory.parent == workflow_data_directory
    assert artifact.video_path.parent == artifact.root_directory / "video"
    assert artifact.frames_directory == artifact.root_directory / "frames"

    loaded = workflows.FrameExtractionArtifact.load(
        artifact.artifact_id, workflow_data_directory
    )
    assert loaded == artifact
    from_flow_run = workflows.FrameExtractionArtifact.from_flow_run(
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
    artifact = workflows.FrameExtractionArtifact.create(workflow_data_directory)
    expected_id = uuid4()
    captured: dict = {}

    async def fake_run_deployment(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id=expected_id)

    monkeypatch.setattr(workflows, "arun_deployment", fake_run_deployment)

    result = asyncio.run(
        workflows.schedule_frame_extraction(
            artifact,
            FrameExtractionSettings(fps=3, fit_in_width=640, fit_in_height=480),
            "owner-1",
        )
    )

    assert result == expected_id
    assert captured["name"] == "frame-extraction/default"
    assert captured["timeout"] == 0
    assert captured["as_subflow"] is False
    assert captured["parameters"] == {
        "artifact_id": str(artifact.artifact_id),
        "video_path": str(artifact.video_path.resolve()),
        "frames_directory": str(artifact.frames_directory.resolve()),
        "fps": 3.0,
        "fit_in_width": 640,
        "fit_in_height": 480,
        "owner_id": "owner-1",
    }


def test_extract_frames_task_sends_ffmpeg_output_to_prefect_run_logger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    records: list[tuple[str, str]] = []

    class FakeRunLogger:
        def info(self, message: str, record: str) -> None:
            records.append((message, record))

    def fake_run_frame_extraction(*args, on_log, **kwargs):
        on_log("frame=1")
        on_log("frame=2")
        return tmp_path / "frames"

    monkeypatch.setattr(workflows, "get_run_logger", lambda: FakeRunLogger())
    monkeypatch.setattr(workflows, "run_frame_extraction", fake_run_frame_extraction)

    result = workflows.extract_frames_task.fn(
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


def test_submit_frame_extraction_stores_upload_and_returns_202(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    workflow_id = uuid4()

    async def fake_schedule(*, artifact, settings, owner_id):
        assert artifact.video_path.read_bytes() == b"video bytes"
        assert artifact.video_path.name == "input.mp4"
        assert settings == FrameExtractionSettings()
        assert owner_id == "owner-1"
        return workflow_id

    monkeypatch.setattr(workflow_views, "schedule_frame_extraction", fake_schedule)

    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("../../unsafe name.MP4", b"video bytes", "video/mp4")},
    )

    assert response.status_code == 202
    assert response.json() == {"workflow_id": str(workflow_id)}


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
    )

    assert response.status_code == 503
    assert list(workflow_data_directory.iterdir()) == []


def test_submit_frame_extraction_rejects_non_video(
    workflow_data_directory: Path, client: TestClient
) -> None:
    response = client.post(
        "/workflows/frame-extraction",
        files={"file": ("input.txt", b"not a video", "text/plain")},
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

    async def fake_get_owned_workflow_run(*args):
        return _flow_run(state_type, message="A status message")

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
    async def fake_get_owned_workflow_run(*args):
        raise workflows.WorkflowNotFoundError

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/status/{uuid4()}")

    assert response.status_code == 404


def test_workflow_result_returns_completed_frames_directory(
    monkeypatch: pytest.MonkeyPatch,
    workflow_data_directory: Path,
    client: TestClient,
) -> None:
    workflow_id = uuid4()
    artifact = workflows.FrameExtractionArtifact.create(workflow_data_directory)
    artifact.frames_directory.mkdir(parents=True)

    async def fake_get_owned_workflow_run(*args):
        return _flow_run(StateType.COMPLETED, artifact_id=artifact.artifact_id)

    monkeypatch.setattr(
        workflow_views, "get_owned_workflow_run", fake_get_owned_workflow_run
    )

    response = client.get(f"/workflows/result/{workflow_id}")

    assert response.status_code == 200
    assert response.json() == {
        "frames_directory": str(artifact.frames_directory.resolve())
    }


def test_workflow_result_returns_409_until_completed(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    async def fake_get_owned_workflow_run(*args):
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

    async def fake_get_owned_workflow_run(*args):
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
    async def fake_get_owned_workflow_run(*args):
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
        workflows, "get_client", lambda: _FakePrefectClientContext(flow_run)
    )

    with pytest.raises(workflows.WorkflowNotFoundError):
        asyncio.run(workflows.get_owned_workflow_run(uuid4(), "owner-1"))
