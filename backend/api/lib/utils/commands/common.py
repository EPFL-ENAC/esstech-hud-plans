import codecs
from collections.abc import Iterator
from pathlib import Path
from typing import Literal, Protocol

type CommandTool = Literal["ffmpeg", "colmap", "brush"]


class BinaryReadStream(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def iter_command_log_records(stream: BinaryReadStream) -> Iterator[str]:
    """Yield UTF-8 command output delimited by newlines or carriage returns."""

    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    record_parts: list[str] = []

    def consume(text: str) -> Iterator[str]:
        for character in text:
            if character in "\r\n":
                record = "".join(record_parts).rstrip()
                record_parts.clear()
                if record:
                    yield record
            else:
                record_parts.append(character)

    while chunk := stream.read(4096):
        yield from consume(decoder.decode(chunk))

    yield from consume(decoder.decode(b"", final=True))
    final_record = "".join(record_parts).rstrip()
    if final_record:
        yield final_record


def workspace_relative_path(path: Path, workspace: Path) -> Path:
    """Return a resolved path relative to its execution workspace."""

    resolved_workspace = workspace.resolve()
    resolved_path = path.resolve()
    try:
        return resolved_path.relative_to(resolved_workspace)
    except ValueError as exc:
        raise ValueError(
            f"Command path must be inside workspace {resolved_workspace}: "
            f"{resolved_path}"
        ) from exc
