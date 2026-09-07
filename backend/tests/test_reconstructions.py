import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from api.db import get_session
from api.lib.workflows import common as workflow_common
from api.lib.workflows import splat_generation as splat_workflow
from api.models.building import Building
from api.models.reconstruction import (
    Reconstruction,
    ReconstructionArtifactUpdate,
    ReconstructionRead,
    ReconstructionStatus,
)
from api.models.user import User
from api.models.workflows import FramePickerSettings, SplatGenerationWorkflowSettings
from api.services.auth import require_user
from api.services.reconstructions import (
    ReconstructionSchedulingError,
    ReconstructionService,
    ReconstructionVideoStorageError,
)
from api.views import buildings as building_views
from api.views import reconstructions as reconstruction_views
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.datastructures import Headers

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
BUILDING_ID = UUID("10000000-0000-0000-0000-000000000001")
OTHER_BUILDING_ID = UUID("10000000-0000-0000-0000-000000000002")
WORKFLOW_ID = UUID("20000000-0000-0000-0000-000000000001")


def _video(filename: str = "scan.mov", content: bytes = b"video bytes") -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": "video/quicktime"}),
    )


@asynccontextmanager
async def reconstruction_service() -> AsyncIterator[
    tuple[ReconstructionService, AsyncSession, AsyncEngine, Building, Building]
]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            first = Building(
                id=BUILDING_ID,
                user_id=USER_ID,
                name="BC",
                latitude=46.518,
                longitude=6.563,
            )
            second = Building(
                id=OTHER_BUILDING_ID,
                user_id=OTHER_USER_ID,
                name="Other",
                latitude=47.0,
                longitude=7.0,
            )
            session.add_all(
                [
                    User(id=USER_ID, keycloak_sub="subject-1"),
                    User(id=OTHER_USER_ID, keycloak_sub="subject-2"),
                    first,
                    second,
                ]
            )
            await session.commit()
            yield ReconstructionService(session), session, engine, first, second
    finally:
        await engine.dispose()


def test_reconstruction_model_boundaries_and_relationship() -> None:
    assert issubclass(ReconstructionRead, BaseModel)
    assert issubclass(ReconstructionArtifactUpdate, BaseModel)
    assert not issubclass(ReconstructionRead, SQLModel)
    assert not issubclass(ReconstructionArtifactUpdate, SQLModel)
    assert Reconstruction.__tablename__ == "reconstructions"
    assert (
        Building.__mapper__.relationships["reconstructions"].back_populates
        == "building"
    )
    assert (
        Reconstruction.__mapper__.relationships["building"].back_populates
        == "reconstructions"
    )


def test_reconstruction_applies_artifact_updates_in_memory() -> None:
    reconstruction = Reconstruction(
        building_id=BUILDING_ID,
        settings={},
        frames_directory="/old/frames",
        splat_path="/old/splat.ply",
    )

    changed = reconstruction.apply_artifact_update_in_memory(
        ReconstructionArtifactUpdate(
            frames_directory="/new/frames",
            splat_path=None,
        )
    )

    assert changed is True
    assert reconstruction.frames_directory == "/new/frames"
    assert reconstruction.splat_path is None
    assert (
        reconstruction.apply_artifact_update_in_memory(
            ReconstructionArtifactUpdate(frames_directory="/new/frames")
        )
        is False
    )


def test_reconstruction_lifecycle_mutations_are_in_memory() -> None:
    reconstruction = Reconstruction(building_id=BUILDING_ID, settings={})

    reconstruction.mark_scheduled_in_memory(WORKFLOW_ID)
    assert reconstruction.status == ReconstructionStatus.SCHEDULED
    assert reconstruction.prefect_workflow_id == WORKFLOW_ID

    assert reconstruction.mark_running_in_memory(WORKFLOW_ID) is True
    assert reconstruction.status == ReconstructionStatus.RUNNING
    assert reconstruction.progress == 0.05

    assert reconstruction.record_progress_in_memory(0.4) is True
    assert reconstruction.progress == 0.4
    assert reconstruction.record_progress_in_memory(0.2) is False
    assert reconstruction.progress == 0.4

    assert (
        reconstruction.mark_terminal_in_memory(
            ReconstructionStatus.FAILED,
            "COLMAP failed",
        )
        is True
    )
    assert reconstruction.status == ReconstructionStatus.FAILED
    assert reconstruction.error_message == "COLMAP failed"
    assert reconstruction.record_progress_in_memory(0.8) is False

    reconstruction.mark_completed_in_memory(
        ReconstructionArtifactUpdate(splat_path="/data/splat.ply")
    )
    assert reconstruction.status == ReconstructionStatus.COMPLETED
    assert reconstruction.progress == 1.0
    assert reconstruction.error_message is None
    assert reconstruction.splat_path == "/data/splat.ply"
    assert (
        reconstruction.mark_terminal_in_memory(
            ReconstructionStatus.CRASHED,
            "late hook",
        )
        is False
    )
    assert reconstruction.status == ReconstructionStatus.COMPLETED


def test_create_from_video_persists_and_schedules_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    settings = SplatGenerationWorkflowSettings(frame_picker=FramePickerSettings())
    captured: dict[str, object] = {}
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path)

    async def fake_schedule(**kwargs: object) -> UUID:
        captured.update(kwargs)
        return WORKFLOW_ID

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation", fake_schedule)

    async def run() -> None:
        async with reconstruction_service() as (service, _, _, building, other):
            reconstruction = await service.create_from_video(
                building=building,
                video=_video(),
                settings=settings,
            )

            assert reconstruction.status == ReconstructionStatus.SCHEDULED
            assert reconstruction.progress == 0.0
            assert reconstruction.prefect_workflow_id == WORKFLOW_ID
            assert reconstruction.settings == settings.model_dump(mode="json")
            assert reconstruction.workspace_directory == str(
                (tmp_path / reconstruction.id.hex).resolve()
            )
            assert reconstruction.input_video_path is not None
            assert Path(reconstruction.input_video_path).read_bytes() == b"video bytes"
            assert reconstruction.raw_frames_directory is None
            assert reconstruction.frames_directory is None
            assert reconstruction.colmap_directory is None
            assert reconstruction.splat_path is None

            artifact = captured["artifact"]
            assert isinstance(artifact, splat_workflow.SplatGenerationArtifact)
            assert artifact.artifact_id == reconstruction.id
            assert captured["owner_id"] == USER_ID
            assert captured["reconstruction_id"] == reconstruction.id
            assert captured["settings"] == settings

            assert (
                await service.get(
                    reconstruction.id,
                    building_id=building.id,
                )
                == reconstruction
            )
            assert (
                await service.get(
                    reconstruction.id,
                    building_id=other.id,
                )
                is None
            )
            assert await service.list(building_id=building.id) == [reconstruction]
            assert await service.list(building_id=other.id) == []

            response = ReconstructionRead.model_validate(reconstruction)
            assert response.settings == settings

    asyncio.run(run())


def test_create_from_video_retains_failed_scheduling_record_and_video(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path)

    async def fail_schedule(**kwargs: object) -> UUID:
        raise RuntimeError("Prefect unavailable")

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation", fail_schedule)

    async def run() -> None:
        async with reconstruction_service() as (service, _, _, building, _):
            with pytest.raises(ReconstructionSchedulingError) as exc_info:
                await service.create_from_video(
                    building=building,
                    video=_video(),
                    settings=SplatGenerationWorkflowSettings(),
                )

            failed = exc_info.value.reconstruction
            assert failed.status == ReconstructionStatus.FAILED
            assert failed.progress == 0.0
            assert failed.prefect_workflow_id is None
            assert failed.error_message == "RuntimeError: Prefect unavailable"
            assert failed.input_video_path is not None
            assert Path(failed.input_video_path).read_bytes() == b"video bytes"
            assert await service.list(building_id=building.id) == [failed]

    asyncio.run(run())


def test_create_from_video_retains_failed_row_and_removes_partial_upload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path)

    async def fail_upload(*args: object, **kwargs: object) -> object:
        reconstruction_id = kwargs["artifact_id"]
        assert isinstance(reconstruction_id, UUID)
        partial = tmp_path / reconstruction_id.hex / "video" / "input.mov"
        partial.parent.mkdir(parents=True)
        partial.write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(
        splat_workflow.SplatGenerationArtifact,
        "from_uploaded_file",
        fail_upload,
    )

    async def run() -> None:
        async with reconstruction_service() as (service, _, _, building, _):
            with pytest.raises(ReconstructionVideoStorageError) as exc_info:
                await service.create_from_video(
                    building=building,
                    video=_video(),
                    settings=SplatGenerationWorkflowSettings(),
                )

            failed = exc_info.value.reconstruction
            assert failed.status == ReconstructionStatus.FAILED
            assert failed.error_message == "OSError: disk full"
            assert failed.input_video_path is None
            assert not (tmp_path / failed.id.hex).exists()

    asyncio.run(run())


def test_scheduling_race_does_not_move_running_record_back_to_scheduled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path)

    async def run() -> None:
        async with reconstruction_service() as (
            service,
            _,
            engine,
            building,
            _,
        ):

            async def start_before_return(**kwargs: object) -> UUID:
                reconstruction_id = kwargs["reconstruction_id"]
                assert isinstance(reconstruction_id, UUID)
                async with AsyncSession(engine, expire_on_commit=False) as race_session:
                    await ReconstructionService(race_session).mark_running(
                        reconstruction_id,
                        prefect_workflow_id=WORKFLOW_ID,
                    )
                return WORKFLOW_ID

            monkeypatch.setattr(
                splat_workflow,
                "schedule_splat_generation",
                start_before_return,
            )
            reconstruction = await service.create_from_video(
                building=building,
                video=_video(),
                settings=SplatGenerationWorkflowSettings(),
            )

            assert reconstruction.status == ReconstructionStatus.RUNNING
            assert reconstruction.progress == 0.05
            assert reconstruction.prefect_workflow_id == WORKFLOW_ID

    asyncio.run(run())


def test_reconstruction_lifecycle_preserves_progress_and_partial_artifacts() -> None:
    async def run() -> None:
        async with reconstruction_service() as (service, session, _, building, _):
            reconstruction = Reconstruction(
                building_id=building.id,
                settings=SplatGenerationWorkflowSettings().model_dump(mode="json"),
            )
            session.add(reconstruction)
            await session.commit()
            await session.refresh(reconstruction)

            running = await service.mark_running(
                reconstruction.id,
                prefect_workflow_id=WORKFLOW_ID,
            )
            assert running.status == ReconstructionStatus.RUNNING
            assert running.progress == 0.05

            progressed = await service.record_progress(
                reconstruction.id,
                progress=0.4,
                artifact_changes=ReconstructionArtifactUpdate(
                    raw_frames_directory="/data/raw",
                    frames_directory="/data/frames",
                ),
            )
            assert progressed.progress == 0.4
            assert progressed.raw_frames_directory == "/data/raw"
            assert progressed.frames_directory == "/data/frames"

            failed = await service.mark_failed(
                reconstruction.id,
                error_message="COLMAP failed",
            )
            assert failed.status == ReconstructionStatus.FAILED
            assert failed.progress == 0.4
            ignored = await service.record_progress(
                reconstruction.id,
                progress=0.9,
                artifact_changes=ReconstructionArtifactUpdate(
                    splat_path="/data/invalid.ply"
                ),
            )
            assert ignored.progress == 0.4
            assert ignored.splat_path is None

            completed_row = Reconstruction(
                building_id=building.id,
                settings=SplatGenerationWorkflowSettings().model_dump(mode="json"),
            )
            session.add(completed_row)
            await session.commit()
            await session.refresh(completed_row)
            completed = await service.mark_completed(
                completed_row.id,
                artifacts=ReconstructionArtifactUpdate(
                    workspace_directory="/data/workspace",
                    input_video_path="/data/input.mp4",
                    frames_directory="/data/frames",
                    colmap_directory="/data/colmap",
                    splat_path="/data/splat.ply",
                ),
            )
            assert completed.status == ReconstructionStatus.COMPLETED
            assert completed.progress == 1.0
            assert completed.splat_path == "/data/splat.ply"

    asyncio.run(run())


def test_reconstruction_list_validates_pagination() -> None:
    async def run() -> None:
        async with reconstruction_service() as (service, _, _, building, _):
            for kwargs in ({"offset": -1}, {"limit": 0}, {"limit": 101}):
                with pytest.raises(ValueError):
                    await service.list(building_id=building.id, **kwargs)

    asyncio.run(run())


@pytest.fixture
def reconstruction_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, UUID]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path)

    async def prepare_database() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add_all(
                [
                    User(id=USER_ID, keycloak_sub="subject-1"),
                    Building(
                        id=BUILDING_ID,
                        user_id=USER_ID,
                        name="BC",
                        latitude=46.518,
                        longitude=6.563,
                    ),
                ]
            )
            await session.commit()

    asyncio.run(prepare_database())

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    async def fake_schedule(**kwargs: object) -> UUID:
        return WORKFLOW_ID

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation", fake_schedule)

    app = FastAPI()
    app.include_router(building_views.router, prefix="/buildings")
    app.include_router(
        reconstruction_views.router,
        prefix="/buildings/{building_id}/reconstructions",
    )
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[require_user] = lambda: User(
        id=USER_ID,
        keycloak_sub="subject-1",
    )

    with TestClient(app) as client:
        yield client, BUILDING_ID

    asyncio.run(engine.dispose())


def _submit_reconstruction(client: TestClient, building_id: UUID):
    return client.post(
        f"/buildings/{building_id}/reconstructions",
        files={"file": ("scan.mp4", b"video bytes", "video/mp4")},
        data={"settings": json.dumps({})},
    )


def test_nested_reconstruction_routes_create_list_and_get(
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api
    response = _submit_reconstruction(client, building_id)

    assert response.status_code == 202
    created = response.json()
    reconstruction_id = created["id"]
    assert created["building_id"] == str(building_id)
    assert created["prefect_workflow_id"] == str(WORKFLOW_ID)
    assert created["status"] == "scheduled"
    assert created["progress"] == 0.0
    assert created["settings"]["ffmpeg"]["fps"] == 2.0
    assert created["workspace_directory"] is not None
    assert created["input_video_path"] is not None

    listed = client.get(f"/buildings/{building_id}/reconstructions")
    assert listed.status_code == 200
    assert listed.json() == [created]

    fetched = client.get(
        f"/buildings/{building_id}/reconstructions/{reconstruction_id}"
    )
    assert fetched.status_code == 200
    assert fetched.json() == created


def _set_artifact_path(
    client: TestClient,
    reconstruction_id: UUID,
    artifact: str,
    path: Path | None,
    *,
    status: ReconstructionStatus | None = None,
) -> None:
    async def update() -> None:
        async for session in client.app.dependency_overrides[get_session]():
            reconstruction = await session.get(Reconstruction, reconstruction_id)
            assert reconstruction is not None
            field = "input_video_path" if artifact == "video" else "splat_path"
            setattr(reconstruction, field, str(path) if path is not None else None)
            if status is not None:
                reconstruction.status = status
                reconstruction.progress = (
                    1.0 if status == ReconstructionStatus.COMPLETED else 0.95
                )
            await session.commit()

    assert client.portal is not None
    client.portal.call(update)


@pytest.fixture(params=["video", "splat"])
def reconstruction_asset(
    request: pytest.FixtureRequest,
    reconstruction_api: tuple[TestClient, UUID],
) -> tuple[TestClient, UUID, str, Path]:
    client, building_id = reconstruction_api
    created = _submit_reconstruction(client, building_id).json()
    reconstruction_id = UUID(created["id"])
    artifact = request.param
    if artifact == "video":
        path = Path(created["input_video_path"])
    else:
        path = Path(created["workspace_directory"]) / "splat.ply"
        path.write_bytes(b"ply\nformat binary_little_endian 1.0\nend_header\n")
        _set_artifact_path(
            client,
            reconstruction_id,
            artifact,
            path,
            status=ReconstructionStatus.COMPLETED,
        )
    return client, reconstruction_id, artifact, path


def _asset_url(reconstruction_id: UUID, artifact: str) -> str:
    return f"/buildings/{BUILDING_ID}/reconstructions/{reconstruction_id}/{artifact}"


def test_reconstruction_assets_serve_inline_bytes_when_available(
    reconstruction_asset: tuple[TestClient, UUID, str, Path],
) -> None:
    client, reconstruction_id, artifact, path = reconstruction_asset
    response = client.get(_asset_url(reconstruction_id, artifact))

    assert response.status_code == 200
    assert response.content == path.read_bytes()
    assert response.headers["content-type"] == (
        "video/mp4" if artifact == "video" else "application/octet-stream"
    )
    assert response.headers["content-disposition"] == f'inline; filename="{path.name}"'
    assert response.headers["content-length"] == str(path.stat().st_size)
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize(
    "status",
    [
        state
        for state in ReconstructionStatus
        if state != ReconstructionStatus.COMPLETED
    ],
)
def test_unfinished_reconstructions_serve_video_but_not_splat(
    reconstruction_asset: tuple[TestClient, UUID, str, Path],
    status: ReconstructionStatus,
) -> None:
    client, reconstruction_id, artifact, path = reconstruction_asset
    _set_artifact_path(client, reconstruction_id, artifact, path, status=status)

    response = client.get(_asset_url(reconstruction_id, artifact))

    if artifact == "video":
        assert response.status_code == 200
        assert response.content == path.read_bytes()
    else:
        # A path recorded at 95% and a physical file do not publish a splat.
        assert response.status_code == 404
        assert response.json() == {"detail": "Reconstruction splat not found"}


@pytest.mark.parametrize(
    "suffix, media_type",
    [
        (".mov", "video/quicktime"),
        (".unknown", "application/octet-stream"),
        (".html", "application/octet-stream"),
    ],
)
def test_reconstruction_video_infers_media_type(
    reconstruction_api: tuple[TestClient, UUID],
    suffix: str,
    media_type: str,
) -> None:
    client, building_id = reconstruction_api
    created = _submit_reconstruction(client, building_id).json()
    reconstruction_id = UUID(created["id"])
    path = Path(created["input_video_path"]).with_suffix(suffix)
    path.write_bytes(b"video bytes")
    _set_artifact_path(client, reconstruction_id, "video", path)

    response = client.get(_asset_url(reconstruction_id, "video"))

    assert response.status_code == 200
    assert response.headers["content-type"] == media_type


def test_reconstruction_assets_support_byte_ranges(
    reconstruction_asset: tuple[TestClient, UUID, str, Path],
) -> None:
    client, reconstruction_id, artifact, path = reconstruction_asset
    url = _asset_url(reconstruction_id, artifact)
    content = path.read_bytes()

    response = client.get(url, headers={"Range": "bytes=1-4"})
    assert response.status_code == 206
    assert response.content == content[1:5]
    assert response.headers["content-range"] == f"bytes 1-4/{len(content)}"
    assert response.headers["content-length"] == "4"

    response = client.get(url, headers={"Range": f"bytes={len(content)}-"})
    assert response.status_code == 416
    assert response.headers["content-range"] == f"*/{len(content)}"


@pytest.mark.parametrize(
    "case",
    [
        "unset",
        "missing",
        "directory",
        "outside",
        "sibling",
        "symlink",
        "workspace_symlink",
    ],
)
def test_reconstruction_assets_reject_unavailable_or_escaped_paths(
    reconstruction_asset: tuple[TestClient, UUID, str, Path],
    tmp_path: Path,
    case: str,
) -> None:
    path: Path | None
    client, reconstruction_id, artifact, path = reconstruction_asset
    if case == "unset":
        path = None
    elif case == "missing":
        path.unlink()
    elif case == "directory":
        path = path.parent
    elif case in {"outside", "sibling", "symlink"}:
        outside = tmp_path / ("outside" if case != "sibling" else uuid4().hex)
        outside.mkdir()
        target = outside / "secret.bin"
        target.write_bytes(b"must not be served")
        if case == "symlink":
            path.unlink()
            path.symlink_to(target)
        elif case == "outside":
            # Keep '..' in the stored path to exercise normalization too.
            path = tmp_path / reconstruction_id.hex / ".." / "outside" / target.name
        else:
            path = target
    elif case == "workspace_symlink":
        workspace = tmp_path / reconstruction_id.hex
        moved = tmp_path / "moved"
        workspace.rename(moved)
        workspace.symlink_to(moved, target_is_directory=True)
    _set_artifact_path(client, reconstruction_id, artifact, path)

    response = client.get(_asset_url(reconstruction_id, artifact))

    assert response.status_code == 404
    assert response.json() == {
        "detail": (
            f"Reconstruction {artifact} not found"
            if case == "unset"
            else "File not found"
        )
    }


def test_reconstruction_assets_require_authentication_and_ownership(
    reconstruction_asset: tuple[TestClient, UUID, str, Path],
) -> None:
    client, reconstruction_id, artifact, _ = reconstruction_asset
    url = _asset_url(reconstruction_id, artifact)
    original = client.app.dependency_overrides.pop(require_user)
    try:
        assert client.get(url).status_code == 401
        client.app.dependency_overrides[require_user] = lambda: User(
            id=OTHER_USER_ID, keycloak_sub="subject-2"
        )
        assert client.get(url).status_code == 404
    finally:
        client.app.dependency_overrides[require_user] = original

    other_building = client.post("/buildings", json={"name": "Other"}).json()
    wrong_parent = url.replace(str(BUILDING_ID), other_building["id"])
    assert client.get(wrong_parent).status_code == 404
    assert client.get(_asset_url(uuid4(), artifact)).status_code == 404


@pytest.mark.parametrize("operation", ["stat", "open"])
def test_reconstruction_assets_map_storage_failures_to_503(
    reconstruction_asset: tuple[TestClient, UUID, str, Path],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    client, reconstruction_id, artifact, path = reconstruction_asset
    original = getattr(Path, operation)

    def fail_access(self: Path, *args: object, **kwargs: object):
        if self == path:
            raise PermissionError(f"Cannot access {path}")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, operation, fail_access)
    response = client.get(_asset_url(reconstruction_id, artifact))

    assert response.status_code == 503
    assert response.json() == {"detail": "File storage is unavailable"}


def test_reconstruction_assets_map_database_failures_to_503(
    reconstruction_asset: tuple[TestClient, UUID, str, Path],
) -> None:
    client, reconstruction_id, artifact, _ = reconstruction_asset

    class FailingReconstructionService(ReconstructionService):
        def __init__(self) -> None:
            pass

        async def get(self, reconstruction_id: UUID, *, building_id: UUID):
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    client.app.dependency_overrides[reconstruction_views.get_reconstruction_service] = (
        FailingReconstructionService
    )
    response = client.get(_asset_url(reconstruction_id, artifact))

    assert response.status_code == 503
    assert response.json() == {"detail": "Reconstruction database is unavailable"}


def test_nested_reconstruction_routes_hide_foreign_building(
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api
    created = _submit_reconstruction(client, building_id).json()

    original_override = client.app.dependency_overrides[require_user]
    client.app.dependency_overrides[require_user] = lambda: User(
        id=OTHER_USER_ID,
        keycloak_sub="subject-2",
    )
    try:
        assert (
            client.get(f"/buildings/{building_id}/reconstructions").status_code == 404
        )
        assert (
            client.get(
                f"/buildings/{building_id}/reconstructions/{created['id']}"
            ).status_code
            == 404
        )
    finally:
        client.app.dependency_overrides[require_user] = original_override


def test_nested_reconstruction_routes_require_authentication(
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api
    original_override = client.app.dependency_overrides.pop(require_user)
    try:
        response = client.get(f"/buildings/{building_id}/reconstructions")
    finally:
        client.app.dependency_overrides[require_user] = original_override

    assert response.status_code == 401


def test_nested_reconstruction_create_validates_video_and_settings(
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api

    wrong_media_type = client.post(
        f"/buildings/{building_id}/reconstructions",
        files={"file": ("scan.txt", b"not video", "text/plain")},
        data={"settings": json.dumps({})},
    )
    invalid_settings = client.post(
        f"/buildings/{building_id}/reconstructions",
        files={"file": ("scan.mp4", b"video", "video/mp4")},
        data={"settings": json.dumps({"ffmpeg": {"fps": 0}})},
    )

    assert wrong_media_type.status_code == 400
    assert invalid_settings.status_code == 422


def test_nested_create_returns_failed_reconstruction_id(
    monkeypatch: pytest.MonkeyPatch,
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api

    async def fail_schedule(**kwargs: object) -> UUID:
        raise RuntimeError("Prefect unavailable")

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation", fail_schedule)
    response = _submit_reconstruction(client, building_id)

    assert response.status_code == 503
    reconstruction_id = response.json()["detail"]["reconstruction_id"]
    listed = client.get(f"/buildings/{building_id}/reconstructions").json()
    assert listed[0]["id"] == reconstruction_id
    assert listed[0]["status"] == "failed"
    assert listed[0]["error_message"] == "RuntimeError: Prefect unavailable"
    assert (
        client.get(
            f"/buildings/{building_id}/reconstructions/{reconstruction_id}/logs"
        ).status_code
        == 409
    )


def test_nested_reconstruction_logs_bridge_to_prefect(
    monkeypatch: pytest.MonkeyPatch,
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api
    reconstruction_id = _submit_reconstruction(client, building_id).json()["id"]

    async def fake_get_owned(workflow_id: UUID, owner_id: UUID):
        assert workflow_id == WORKFLOW_ID
        assert owner_id == USER_ID
        return SimpleNamespace(id=workflow_id)

    class Item:
        def to_sse_event(self) -> str:
            return 'event: log\ndata: {"message":"started"}\n\n'

    async def fake_stream(flow_run: object):
        yield Item()

    monkeypatch.setattr(reconstruction_views, "get_owned_workflow_run", fake_get_owned)
    monkeypatch.setattr(reconstruction_views, "stream_workflow_logs", fake_stream)

    response = client.get(
        f"/buildings/{building_id}/reconstructions/{reconstruction_id}/logs"
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert '"message":"started"' in response.text


def test_nested_reconstruction_logs_map_prefect_failure_to_503(
    monkeypatch: pytest.MonkeyPatch,
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api
    reconstruction_id = _submit_reconstruction(client, building_id).json()["id"]

    async def fail_get_owned(workflow_id: UUID, owner_id: UUID):
        raise OSError("Prefect offline")

    monkeypatch.setattr(reconstruction_views, "get_owned_workflow_run", fail_get_owned)

    response = client.get(
        f"/buildings/{building_id}/reconstructions/{reconstruction_id}/logs"
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Workflow service is unavailable"}


def test_nested_reconstruction_routes_map_database_failures_to_503(
    reconstruction_api: tuple[TestClient, UUID],
) -> None:
    client, building_id = reconstruction_api

    class FailingReconstructionService(ReconstructionService):
        def __init__(self) -> None:
            pass

        async def list(self, **kwargs: object) -> list[Reconstruction]:
            raise OperationalError("SELECT", {}, RuntimeError("offline"))

    client.app.dependency_overrides[reconstruction_views.get_reconstruction_service] = (
        FailingReconstructionService
    )

    response = client.get(f"/buildings/{building_id}/reconstructions")

    assert response.status_code == 503
    assert response.json() == {"detail": "Reconstruction database is unavailable"}


def test_schedule_reconstruction_uses_prefect_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    reconstruction_id = uuid4()
    artifact = splat_workflow.SplatGenerationArtifact.create(
        tmp_path,
        artifact_id=reconstruction_id,
    )

    async def fake_run_deployment(**kwargs: object):
        captured.update(kwargs)
        return SimpleNamespace(id=WORKFLOW_ID)

    monkeypatch.setattr(splat_workflow, "arun_deployment", fake_run_deployment)

    result = asyncio.run(
        splat_workflow.schedule_splat_generation(
            artifact,
            SplatGenerationWorkflowSettings(),
            USER_ID,
            reconstruction_id=reconstruction_id,
        )
    )

    assert result == WORKFLOW_ID
    assert captured["idempotency_key"] == f"reconstruction:{reconstruction_id}"
    parameters = captured["parameters"]
    assert isinstance(parameters, dict)
    assert parameters["reconstruction_id"] == str(reconstruction_id)


@pytest.mark.parametrize("use_frame_picker", [False, True])
def test_reconstruction_flow_records_milestones_and_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    use_frame_picker: bool,
) -> None:
    updates: list[tuple[float, ReconstructionArtifactUpdate | None]] = []
    reconstruction_id = uuid4()
    settings = SplatGenerationWorkflowSettings(
        frame_picker=FramePickerSettings() if use_frame_picker else None
    )

    class FakeRunLogger:
        def info(self, *args: object) -> None:
            pass

    async def capture_progress(
        received_id: UUID | None,
        *,
        progress: float,
        artifacts: ReconstructionArtifactUpdate | None = None,
    ) -> None:
        assert received_id == reconstruction_id
        updates.append((progress, artifacts))

    monkeypatch.setattr(splat_workflow, "get_run_logger", lambda: FakeRunLogger())
    monkeypatch.setattr(
        splat_workflow,
        "_record_reconstruction_progress",
        capture_progress,
    )
    monkeypatch.setattr(
        splat_workflow,
        "extract_frames_task",
        lambda **kwargs: kwargs["frames_directory"],
    )
    monkeypatch.setattr(
        splat_workflow,
        "pick_frames_task",
        lambda **kwargs: str(tmp_path / "frames"),
    )
    monkeypatch.setattr(
        splat_workflow,
        "reconstruct_with_colmap_task",
        lambda **kwargs: str(tmp_path / "colmap"),
    )
    monkeypatch.setattr(
        splat_workflow,
        "train_with_brush_task",
        lambda **kwargs: str(tmp_path / "splat.ply"),
    )

    result = asyncio.run(
        splat_workflow.splat_generation_flow.fn(
            artifact_id=reconstruction_id,
            workspace_directory=str(tmp_path),
            video_path=str(tmp_path / "input.mp4"),
            raw_frames_directory=str(tmp_path / "raw"),
            frames_directory=str(tmp_path / "frames"),
            colmap_directory=str(tmp_path / "colmap"),
            splat_path=str(tmp_path / "splat.ply"),
            settings=settings,
            owner_id=USER_ID,
            reconstruction_id=reconstruction_id,
        )
    )

    assert result == str(tmp_path / "splat.ply")
    assert [progress for progress, _ in updates] == [0.25, 0.4, 0.7, 0.95]
    first_artifacts = updates[0][1]
    assert first_artifacts is not None
    if use_frame_picker:
        assert first_artifacts.raw_frames_directory == str(tmp_path / "raw")
        assert first_artifacts.frames_directory is None
    else:
        assert first_artifacts.raw_frames_directory is None
        assert first_artifacts.frames_directory == str(tmp_path / "frames")
    assert updates[-1][1] == ReconstructionArtifactUpdate(
        splat_path=str(tmp_path / "splat.ply")
    )


def test_reconstruction_flow_hooks_publish_terminal_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    reconstruction_id = uuid4()
    flow_run = SimpleNamespace(
        id=WORKFLOW_ID,
        parameters={
            "reconstruction_id": str(reconstruction_id),
            "workspace_directory": "/data/workspace",
            "video_path": "/data/input.mp4",
            "raw_frames_directory": "/data/raw",
            "frames_directory": "/data/frames",
            "colmap_directory": "/data/colmap",
            "splat_path": "/data/splat.ply",
            "settings": {"frame_picker": {}},
        },
    )

    class FakeReconstructionService:
        async def mark_running(self, received_id: UUID, **kwargs: object) -> None:
            assert received_id == reconstruction_id
            calls.append(("running", kwargs["prefect_workflow_id"]))

        async def mark_completed(self, received_id: UUID, **kwargs: object) -> None:
            assert received_id == reconstruction_id
            calls.append(("completed", kwargs["artifacts"]))

        async def mark_failed(self, received_id: UUID, **kwargs: object) -> None:
            assert received_id == reconstruction_id
            calls.append(("failed", kwargs["error_message"]))

        async def mark_cancelled(self, received_id: UUID, **kwargs: object) -> None:
            assert received_id == reconstruction_id
            calls.append(("cancelled", kwargs["error_message"]))

        async def mark_crashed(self, received_id: UUID, **kwargs: object) -> None:
            assert received_id == reconstruction_id
            calls.append(("crashed", kwargs["error_message"]))

    @asynccontextmanager
    async def fake_service_context():
        yield FakeReconstructionService()

    monkeypatch.setattr(
        splat_workflow,
        "_reconstruction_service",
        fake_service_context,
    )
    state = SimpleNamespace(message="state message", name="State")

    async def run() -> None:
        await splat_workflow._reconstruction_running_hook(None, flow_run, state)
        await splat_workflow._reconstruction_completed_hook(None, flow_run, state)
        await splat_workflow._reconstruction_failed_hook(None, flow_run, state)
        await splat_workflow._reconstruction_cancelled_hook(None, flow_run, state)
        await splat_workflow._reconstruction_crashed_hook(None, flow_run, state)

    asyncio.run(run())

    assert calls[0] == ("running", WORKFLOW_ID)
    assert calls[1] == (
        "completed",
        ReconstructionArtifactUpdate(
            workspace_directory="/data/workspace",
            input_video_path="/data/input.mp4",
            raw_frames_directory="/data/raw",
            frames_directory="/data/frames",
            colmap_directory="/data/colmap",
            splat_path="/data/splat.ply",
        ),
    )
    assert calls[2:] == [
        ("failed", "state message"),
        ("cancelled", "state message"),
        ("crashed", "state message"),
    ]
