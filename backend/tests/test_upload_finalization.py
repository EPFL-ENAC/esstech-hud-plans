import asyncio
import hashlib
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from api.config import config
from api.db import get_session
from api.lib.uploads import paths
from api.lib.workflows import common as workflow_common
from api.lib.workflows import splat_generation as splat_workflow
from api.models.building import Building
from api.models.user import User
from api.services.auth import require_user
from api.views import uploads as uploads_view
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

USER_ID = UUID("00000000-0000-0000-0000-000000000001")
BUILDING_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKFLOW_ID = UUID("20000000-0000-0000-0000-000000000001")
CHUNK_SIZE = 8
TOTAL_SIZE = 17


def _chunk_body(index: int, size: int) -> bytes:
    return bytes([index]) * size


def _chunk_digest(index: int, size: int) -> str:
    return hashlib.sha256(_chunk_body(index, size)).hexdigest()


def _chunk_plan(total_size: int = TOTAL_SIZE) -> list[dict[str, object]]:
    plan = []
    offset = 0
    index = 0
    while offset < total_size:
        size = min(CHUNK_SIZE, total_size - offset)
        plan.append(
            {"index": index, "size": size, "sha256": _chunk_digest(index, size)}
        )
        offset += size
        index += 1
    return plan


def _chunk_sizes(total_size: int = TOTAL_SIZE) -> list[int]:
    return [
        min(CHUNK_SIZE, total_size - offset)
        for offset in range(0, total_size, CHUNK_SIZE)
    ]


def _create_payload(
    *,
    building_id: UUID | None = BUILDING_ID,
    building: dict[str, object] | None = None,
    total_size: int = TOTAL_SIZE,
) -> dict[str, object]:
    values: dict[str, object] = {
        "filename": "video.mp4",
        "total_size": total_size,
        "chunk_size": CHUNK_SIZE,
        "settings": {},
        "chunks": _chunk_plan(total_size),
    }
    if building_id is not None:
        values["building_id"] = str(building_id)
    if building is not None:
        values["building"] = building
    return values


@pytest.fixture
def finalize_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, AsyncEngine, Path]]:
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_TEMP_DIR", str(tmp_path / "staging"))
    monkeypatch.setattr(config, "UPLOAD_CHUNK_SIZE_BYTES", CHUNK_SIZE)

    async def fake_schedule(**kwargs: object) -> UUID:
        return WORKFLOW_ID

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation", fake_schedule)

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
    )

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

    app = FastAPI()
    app.include_router(uploads_view.router, prefix="/uploads")
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[require_user] = lambda: User(
        id=USER_ID,
        keycloak_sub="subject-1",
    )

    with TestClient(app) as client:
        yield client, engine, tmp_path

    asyncio.run(engine.dispose())


def _create_and_put_all(
    client: TestClient,
    *,
    building: dict[str, object] | None = None,
) -> UUID:
    building_id = None if building is not None else BUILDING_ID
    values = _create_payload(building_id=building_id, building=building)
    created = client.post("/uploads", json=values).json()
    session_id = UUID(created["session_id"])
    for index, size in enumerate(_chunk_sizes()):
        response = client.put(
            f"/uploads/{session_id}/chunks/{index}",
            content=_chunk_body(index, size),
        )
        assert response.status_code == 200
    return session_id


def test_finalize_assembles_unordered_chunks_and_cleans_up(
    finalize_api: tuple[TestClient, AsyncEngine, Path],
) -> None:
    client, _, data_root = finalize_api
    values = _create_payload()
    created = client.post("/uploads", json=values).json()
    session_id = UUID(created["session_id"])
    for index in (2, 1, 0):
        size = _chunk_sizes()[index]
        response = client.put(
            f"/uploads/{session_id}/chunks/{index}",
            content=_chunk_body(index, size),
        )
        assert response.status_code == 200

    response = client.post(f"/uploads/{session_id}/finalize")

    assert response.status_code == 200
    body = response.json()
    assert body["building_id"] == str(BUILDING_ID)
    assert body["status"] == "scheduled"
    assert body["input_video_path"] is not None
    video = Path(body["input_video_path"])
    assert video.read_bytes() == b"".join(
        _chunk_body(index, size) for index, size in enumerate(_chunk_sizes())
    )
    assert data_root in video.resolve().parents

    # The session rows and staging dir are cleaned after a successful submit.
    fetched = client.get(f"/uploads/{session_id}")
    assert fetched.status_code == 404
    assert not paths.session_dir(session_id).exists()


def test_finalize_creates_the_building_from_payload(
    finalize_api: tuple[TestClient, AsyncEngine, Path],
) -> None:
    client, _, _ = finalize_api
    session_id = _create_and_put_all(
        client, building={"name": "BC", "latitude": None, "longitude": None}
    )

    response = client.post(f"/uploads/{session_id}/finalize")

    assert response.status_code == 200
    body = response.json()
    assert body["building"]["name"] == "BC"
    assert body["reconstruction"]["building_id"] == body["building"]["id"]
    assert body["reconstruction"]["status"] == "scheduled"
    assert client.get(f"/uploads/{session_id}").status_code == 404


def test_finalize_rejects_incomplete_sessions(
    finalize_api: tuple[TestClient, AsyncEngine, Path],
) -> None:
    client, _, _ = finalize_api
    values = _create_payload()
    created = client.post("/uploads", json=values).json()
    session_id = UUID(created["session_id"])
    response = client.put(
        f"/uploads/{session_id}/chunks/0", content=_chunk_body(0, CHUNK_SIZE)
    )
    assert response.status_code == 200

    response = client.post(f"/uploads/{session_id}/finalize")

    assert response.status_code == 409
    assert response.json()["detail"]["missing_chunks"] == [1, 2]
    assert client.get(f"/uploads/{session_id}").status_code == 200


def test_finalize_keeps_the_session_alive_when_scheduling_fails(
    finalize_api: tuple[TestClient, AsyncEngine, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = finalize_api
    session_id = _create_and_put_all(client)

    async def fail_schedule(**kwargs: object) -> UUID:
        raise RuntimeError("Prefect unavailable")

    monkeypatch.setattr(splat_workflow, "schedule_splat_generation", fail_schedule)

    response = client.post(f"/uploads/{session_id}/finalize")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["building_id"] == str(BUILDING_ID)
    assert "reconstruction_id" in detail
    # The session stays alive so the caller can inspect or delete it.
    assert client.get(f"/uploads/{session_id}").status_code == 200


def test_finalize_keeps_the_session_alive_when_storage_fails(
    finalize_api: tuple[TestClient, AsyncEngine, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = finalize_api
    session_id = _create_and_put_all(client)

    def fail_create(*args: object, **kwargs: object) -> object:
        raise OSError("disk full")

    monkeypatch.setattr(splat_workflow.SplatGenerationArtifact, "create", fail_create)

    response = client.post(f"/uploads/{session_id}/finalize")

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["message"] == "Failed to store reconstruction video"
    assert "reconstruction_id" in detail
    assert client.get(f"/uploads/{session_id}").status_code == 200


def test_finalize_maps_assembly_size_mismatch_to_500(
    finalize_api: tuple[TestClient, AsyncEngine, Path],
) -> None:
    client, _, _ = finalize_api
    session_id = _create_and_put_all(client)

    # Corrupt one stored part so its size no longer matches the plan.
    part = paths.part_file(session_id, 1)
    part.write_bytes(b"corrupt")

    response = client.post(f"/uploads/{session_id}/finalize")

    assert response.status_code == 500
    assert client.get(f"/uploads/{session_id}").status_code == 200


def test_finalize_twice_returns_not_found(
    finalize_api: tuple[TestClient, AsyncEngine, Path],
) -> None:
    client, _, _ = finalize_api
    session_id = _create_and_put_all(client)

    first = client.post(f"/uploads/{session_id}/finalize")
    second = client.post(f"/uploads/{session_id}/finalize")

    assert first.status_code == 200
    assert second.status_code == 404
