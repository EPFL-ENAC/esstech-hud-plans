from pathlib import Path
from uuid import uuid4

import pytest

from api.config import config
from api.lib import upload_storage


def test_upload_path_uses_uuid_and_lowercase_extension(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    upload_id = uuid4()
    assert upload_storage.upload_file_path(upload_id, "../../scan.MOV") == (
        tmp_path / "uploads" / upload_id.hex / "input.mov"
    )


def test_copy_reuses_atomically_published_destination(tmp_path: Path) -> None:
    source = tmp_path / "missing-source"
    destination = tmp_path / "stored.mp4"
    destination.write_bytes(b"video bytes")
    upload_storage.copy_completed_file(source, destination, 11)
    assert destination.read_bytes() == b"video bytes"


@pytest.mark.parametrize("case", ["missing", "empty", "short", "directory"])
def test_copy_rejects_incomplete_source(tmp_path: Path, case: str) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "stored.mp4"
    if case == "directory":
        source.mkdir()
    elif case != "missing":
        source.write_bytes(b"" if case == "empty" else b"partial")
    with pytest.raises(OSError):
        upload_storage.copy_completed_file(source, destination, 11)
    assert not destination.exists()
    assert not destination.with_suffix(".mp4.tmp").exists()


@pytest.mark.parametrize("failure", ["copy", "rename", "truncated"])
def test_failed_copy_keeps_source_and_removes_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: str,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "stored" / "input.mp4"
    source.write_bytes(b"video bytes")

    def fail_copy(source: Path, temporary: Path) -> None:
        temporary.write_bytes(b"partial")
        if failure == "copy":
            raise OSError("Disk full")

    def fail_rename(source: Path, destination: Path) -> None:
        raise OSError("Rename failed")

    if failure == "rename":
        monkeypatch.setattr(upload_storage.os, "replace", fail_rename)
    else:
        monkeypatch.setattr(upload_storage.shutil, "copyfile", fail_copy)

    with pytest.raises(OSError):
        upload_storage.copy_completed_file(source, destination, 11)
    assert source.read_bytes() == b"video bytes"
    assert not destination.exists()
    assert not destination.with_suffix(".mp4.tmp").exists()


def test_copy_does_not_overwrite_invalid_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "stored.mp4"
    source.write_bytes(b"video bytes")
    destination.write_bytes(b"invalid")
    with pytest.raises(OSError):
        upload_storage.copy_completed_file(source, destination, 11)
    assert destination.read_bytes() == b"invalid"
    assert source.read_bytes() == b"video bytes"
