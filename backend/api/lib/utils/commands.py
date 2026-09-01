import codecs
import logging
import subprocess
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

type LogCallback = Callable[[str], None]
type CommandLogCapture = Literal["stdout", "stderr", "combined"]
type CommandLogStream = Literal["stdout", "stderr"]


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


@dataclass(frozen=True)
class _CommandSettings:
    stdout: int
    stderr: int
    log_stream: CommandLogStream


_COMMAND_SETTINGS: dict[CommandLogCapture, _CommandSettings] = {
    "stdout": _CommandSettings(
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        log_stream="stdout",
    ),
    "stderr": _CommandSettings(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        log_stream="stderr",
    ),
    "combined": _CommandSettings(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        log_stream="stdout",
    ),
}


def run_logged_command(
    command: Sequence[str],
    *,
    capture: CommandLogCapture,
    log_prefix: str,
    fallback_logger: logging.Logger,
    on_log: LogCallback | None = None,
) -> None:
    command = list(command)

    settings = _COMMAND_SETTINGS.get(capture)
    if settings is None:
        raise ValueError(f"Unsupported command log capture mode: {capture}")

    fallback_logger.info("Running %s command: %s", log_prefix, command)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=settings.stdout,
        stderr=settings.stderr,
    )
    emit_log = on_log or (
        lambda record: fallback_logger.info("%s: %s", log_prefix, record)
    )

    try:
        stream = process.stdout if settings.log_stream == "stdout" else process.stderr
        if stream is None:
            raise RuntimeError(f"{settings.log_stream} was not captured")

        for record in iter_command_log_records(stream):
            emit_log(record)
    except BaseException:
        if process.poll() is None:
            process.terminate()
        process.wait()
        raise

    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, command)
