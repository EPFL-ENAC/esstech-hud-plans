import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from api.config import config
from api.db import get_session
from api.lib.uploads import paths
from api.lib.workflows import common as workflow_common
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
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000002")
BUILDING_ID = UUID("10000000-0000-0000-0000-000000000001")

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


def _create_payload(
    *,
    building_id: UUID | None = BUILDING_ID,
    building: dict[str, object] | None = None,
    total_size: int = TOTAL_SIZE,
    filename: str = "video.mp4",
    chunk_plan: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    values: dict[str, object] = {
        "filename": filename,
        "total_size": total_size,
        "chunk_size": CHUNK_SIZE,
        "settings": {},
        "chunks": _chunk_plan(total_size) if chunk_plan is None else chunk_plan,
    }
    if building_id is not None:
        values["building_id"] = str(building_id)
    if building is not None:
        values["building"] = building
    return values


def _chunk_sizes(total_size: int = TOTAL_SIZE) -> list[int]:
    return [
        min(CHUNK_SIZE, total_size - offset)
        for offset in range(0, total_size, CHUNK_SIZE)
    ]


def _create_and_put_all(client: TestClient, *, building: dict | None = None) -> UUID:
    values = _create_payload(
        building=building, building_id=None if building else BUILDING_ID
    )
    created = client.post("/uploads", json=values).json()
    session_id = UUID(created["session_id"])
    for index, size in enumerate(_chunk_sizes()):
        response = client.put(
            f"/uploads/{session_id}/chunks/{index}", content=_chunk_body(index, size)
        )
        assert response.status_code == 200
    return session_id


@pytest.fixture
def upload_api(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, AsyncEngine]]:
    monkeypatch.setattr(workflow_common, "WORKFLOW_DATA_DIRECTORY", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_TEMP_DIR", str(tmp_path / "staging"))
    monkeypatch.setattr(config, "UPLOAD_CHUNK_SIZE_BYTES", CHUNK_SIZE)

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
        yield client, engine

    asyncio.run(engine.dispose())


def test_create_upload_session_happy_path(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    response = client.post("/uploads", json=_create_payload())

    assert response.status_code == 201
    state = response.json()
    assert state["status"] == "uploading"
    assert state["chunk_size"] == CHUNK_SIZE
    assert state["total_chunks"] == 3
    assert state["received_bytes"] == 0
    assert state["missing_chunks"] == [0, 1, 2]
    assert state["expires_at"]

    fetched = client.get(f"/uploads/{state['session_id']}")
    assert fetched.status_code == 200
    assert fetched.json() == state


def test_create_upload_session_rejects_bad_chunk_plans(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api

    missing_chunk = _chunk_plan()[:-1]
    response = client.post("/uploads", json=_create_payload(chunk_plan=missing_chunk))
    assert response.status_code == 422

    wrong_size = _chunk_plan()
    wrong_size[1]["size"] = 7
    response = client.post("/uploads", json=_create_payload(chunk_plan=wrong_size))
    assert response.status_code == 422

    wrong_digest = _chunk_plan()
    wrong_digest[0]["sha256"] = "z" * 64
    response = client.post("/uploads", json=_create_payload(chunk_plan=wrong_digest))
    assert response.status_code == 422


def test_create_upload_session_requires_exactly_one_building_input(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api

    both = _create_payload(building_id=BUILDING_ID, building={"name": "BC"})
    assert client.post("/uploads", json=both).status_code == 422

    neither = _create_payload(building_id=None)
    assert client.post("/uploads", json=neither).status_code == 422


def test_create_upload_session_rejects_unknown_building(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    response = client.post("/uploads", json=_create_payload(building_id=uuid4()))
    assert response.status_code == 404


def test_create_upload_session_validates_video_files(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    response = client.post("/uploads", json=_create_payload(filename="notes.txt"))
    assert response.status_code == 422

    accepted = client.post("/uploads", json=_create_payload(filename="clip"))
    assert accepted.status_code == 201


def test_put_chunk_stores_the_bytes(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    session_id = UUID(created["session_id"])

    response = client.put(
        f"/uploads/{session_id}/chunks/0",
        content=_chunk_body(0, CHUNK_SIZE),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["received_bytes"] == CHUNK_SIZE
    assert result["missing_chunks_count"] == 2

    stored = paths.part_file(session_id, 0)
    assert stored.read_bytes() == _chunk_body(0, CHUNK_SIZE)

    fetched = client.get(f"/uploads/{session_id}").json()
    assert fetched["missing_chunks"] == [1, 2]


def test_put_chunk_rejects_size_and_digest_mismatches(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    session_id = UUID(created["session_id"])

    short = client.put(
        f"/uploads/{session_id}/chunks/0",
        content=_chunk_body(0, CHUNK_SIZE - 1),
    )
    assert short.status_code == 400
    assert not paths.part_file(session_id, 0).exists()

    different_bytes = client.put(
        f"/uploads/{session_id}/chunks/0",
        content=bytes([9]) * CHUNK_SIZE,
    )
    assert different_bytes.status_code == 400
    assert not paths.part_file(session_id, 0).exists()
    assert (
        different_bytes.json()["detail"]
        == "Chunk digest does not match the upload plan"
    )


def test_put_chunk_rejects_a_body_longer_than_the_plan(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    session_id = UUID(created["session_id"])

    response = client.put(
        f"/uploads/{session_id}/chunks/0",
        content=bytes([7]) * (CHUNK_SIZE + 1),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 400
    assert not paths.part_file(session_id, 0).exists()
    assert response.json()["detail"] == "Chunk size does not match the upload plan"


def test_put_chunk_is_idempotent_for_received_chunks(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    session_id = UUID(created["session_id"])

    first = client.put(
        f"/uploads/{session_id}/chunks/0", content=_chunk_body(0, CHUNK_SIZE)
    )
    again = client.put(
        f"/uploads/{session_id}/chunks/0", content=_chunk_body(0, CHUNK_SIZE)
    )

    assert first.status_code == 200
    assert again.status_code == 200
    assert again.json() == first.json()


def test_put_chunk_rejects_unknown_indexes(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    response = client.put(
        f"/uploads/{created['session_id']}/chunks/9",
        content=_chunk_body(9, CHUNK_SIZE),
    )
    assert response.status_code == 404


def test_put_chunk_is_scoped_to_the_owner(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    original = client.app.dependency_overrides.pop(require_user)
    try:
        client.app.dependency_overrides[require_user] = lambda: User(
            id=OTHER_USER_ID, keycloak_sub="subject-2"
        )
        response = client.put(
            f"/uploads/{created['session_id']}/chunks/0",
            content=_chunk_body(0, CHUNK_SIZE),
        )
        assert response.status_code == 404
        assert client.get(f"/uploads/{created['session_id']}").status_code == 404
    finally:
        client.app.dependency_overrides[require_user] = original


def test_expired_sessions_reject_chunk_uploads(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, engine = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    session_id = UUID(created["session_id"])

    async def expire() -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            from api.models.uploads import UploadSession

            row = await session.get(UploadSession, session_id)
            assert row is not None
            row.expires_at = datetime.now(UTC) - timedelta(hours=1)
            await session.commit()

    asyncio.run(expire())

    assert (
        client.put(
            f"/uploads/{session_id}/chunks/0", content=_chunk_body(0, CHUNK_SIZE)
        ).status_code
        == 410
    )
    assert client.get(f"/uploads/{session_id}").status_code == 410


def test_finalized_sessions_reject_chunk_uploads(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, engine = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    session_id = UUID(created["session_id"])

    async def finalize_rows() -> None:
        from api.models.uploads import UploadSession, UploadSessionStatus

        async with AsyncSession(engine, expire_on_commit=False) as session:
            row = await session.get(UploadSession, session_id)
            assert row is not None
            row.status = UploadSessionStatus.FINALIZED
            await session.commit()

    asyncio.run(finalize_rows())

    assert (
        client.put(
            f"/uploads/{session_id}/chunks/0", content=_chunk_body(0, CHUNK_SIZE)
        ).status_code
        == 409
    )


def test_delete_upload_session_removes_rows_and_files(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    created = client.post("/uploads", json=_create_payload()).json()
    session_id = UUID(created["session_id"])
    paths.make_session_temp_dir(session_id)

    response = client.delete(f"/uploads/{session_id}")

    assert response.status_code == 204
    assert client.get(f"/uploads/{session_id}").status_code == 404
    assert not paths.session_dir(session_id).exists()


def test_upload_routes_require_authentication(
    upload_api: tuple[TestClient, AsyncEngine],
) -> None:
    client, _ = upload_api
    original = client.app.dependency_overrides.pop(require_user)
    try:
        assert client.post("/uploads", json=_create_payload()).status_code == 401
    finally:
        client.app.dependency_overrides[require_user] = original
