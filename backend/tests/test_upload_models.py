import uuid
from uuid import UUID

import pytest
from api.models.uploads import (
    ChunkPlanEntry,
    UploadChunk,
    UploadSession,
    UploadSessionCreate,
    UploadSessionStatus,
)
from api.services.uploads import build_chunk_rows
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

DIGEST = "a" * 64


def _plan(total_size: int, chunk_size: int) -> list[ChunkPlanEntry]:
    entries = []
    offset = 0
    index = 0
    while offset < total_size:
        size = min(chunk_size, total_size - offset)
        entries.append(ChunkPlanEntry(index=index, size=size, sha256=DIGEST))
        offset += size
        index += 1
    return entries


def _payload(**overrides: object) -> UploadSessionCreate:
    raw_total = overrides.get("total_size", 17)
    raw_chunk = overrides.get("chunk_size", 8)
    total_size = int(raw_total) if isinstance(raw_total, int) else 17
    chunk_size = int(raw_chunk) if isinstance(raw_chunk, int) else 8
    values: dict[str, object] = {
        "filename": "video.mp4",
        "total_size": total_size,
        "chunk_size": chunk_size,
        "chunks": _plan(total_size, chunk_size),
        "building_id": None,
        "building": {"name": "BC"},
    }
    values.update(overrides)
    return UploadSessionCreate(**values)


def _session(
    *,
    user_id: UUID | None = None,
    **overrides: object,
) -> UploadSession:
    values: dict[str, object] = {
        "user_id": user_id or uuid.uuid4(),
        "settings": {},
        "filename": "video.mp4",
        "file_extension": "mp4",
        "total_size": 10,
        "chunk_size": 8,
        "total_chunks": 2,
    }
    values.update(overrides)
    return UploadSession(**values)


def test_upload_session_defaults() -> None:
    row = _session()
    assert row.status == UploadSessionStatus.UPLOADING
    assert row.received_bytes == 0
    assert row.expires_at is not None
    assert row.building_id is None
    assert row.building_payload is None


def test_upload_session_check_constraints() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with pytest.raises(IntegrityError):
        with Session(engine) as db:
            db.add(_session(received_bytes=100))
            db.commit()
    with pytest.raises(IntegrityError):
        with Session(engine) as db:
            db.add(_session(total_chunks=0))
            db.commit()
    with pytest.raises(IntegrityError):
        with Session(engine) as db:
            db.add(_session(status="bogus"))
            db.commit()


def test_upload_chunks_composite_primary_key() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    session_id = uuid.uuid4()
    with Session(engine) as db:
        db.add(_session(id=session_id))
        db.commit()
        db.add(
            UploadChunk(
                session_id=session_id,
                chunk_index=0,
                byte_offset=0,
                expected_size=8,
                expected_digest=DIGEST,
            )
        )
        db.commit()
        with pytest.raises(IntegrityError):
            db.add(
                UploadChunk(
                    session_id=session_id,
                    chunk_index=0,
                    byte_offset=0,
                    expected_size=8,
                    expected_digest=DIGEST,
                )
            )
            db.commit()


def test_build_chunk_rows_builds_the_declared_plan() -> None:
    payload = _payload(total_size=17, chunk_size=8)
    rows = build_chunk_rows(payload, chunk_size=8)
    assert [row.chunk_index for row in rows] == [0, 1, 2]
    assert [row.byte_offset for row in rows] == [0, 8, 16]
    assert [row.expected_size for row in rows] == [8, 8, 1]
    assert [row.expected_digest for row in rows] == [DIGEST] * 3


def test_build_chunk_rows_rejects_mismatched_counts() -> None:
    payload = _payload(total_size=17, chunk_size=8)
    payload.chunks = payload.chunks[:-1]
    with pytest.raises(ValueError):
        build_chunk_rows(payload, chunk_size=8)


def test_build_chunk_rows_rejects_mismatched_sizes() -> None:
    payload = _payload(total_size=17, chunk_size=8)
    payload.chunks[1].size = 7
    with pytest.raises(ValueError):
        build_chunk_rows(payload, chunk_size=8)


def test_build_chunk_rows_computes_a_single_partial_chunk() -> None:
    payload = _payload(total_size=1, chunk_size=8)
    rows = build_chunk_rows(payload, chunk_size=8)
    assert [row.expected_size for row in rows] == [1]
