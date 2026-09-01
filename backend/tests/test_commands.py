import io
import logging
import subprocess

import pytest
from api.lib.utils import commands
from api.lib.utils.commands import iter_command_log_records


class _ChunkedStream:
    def __init__(self, chunks: list[bytes]):
        self.chunks = iter(chunks)

    def read(self, size: int = -1) -> bytes:
        return next(self.chunks, b"")


class _FakeProcess:
    def __init__(
        self,
        return_code: int = 0,
        *,
        stdout: bytes = b"stdout record\n",
        stderr: bytes = b"stderr record\n",
    ):
        self.return_code = return_code
        self.stdout: commands.BinaryReadStream = io.BytesIO(stdout)
        self.stderr: commands.BinaryReadStream = io.BytesIO(stderr)
        self.waited = False
        self.terminated = False

    def wait(self) -> int:
        self.waited = True
        return self.return_code

    def poll(self) -> int | None:
        return self.return_code if self.waited else None

    def terminate(self) -> None:
        self.terminated = True


class _FakeLogger(logging.Logger):
    def __init__(self) -> None:
        super().__init__("test-command-logger")
        self.records: list[tuple[object, ...]] = []

    def info(self, msg: object, *args: object, **kwargs: object) -> None:
        self.records.append((msg, *args))


class _FailingStream:
    def read(self, size: int = -1) -> bytes:
        raise OSError("Could not read command output")


def test_iter_command_log_records_normalizes_stream_boundaries() -> None:
    stream = _ChunkedStream(
        [
            b"header\nprogress=1\r\n\r",
            b"\xe2\x98",
            b"\x83\nfinal record",
        ]
    )

    assert list(iter_command_log_records(stream)) == [
        "header",
        "progress=1",
        "☃",
        "final record",
    ]


@pytest.mark.parametrize(
    ("capture", "expected_stdout", "expected_stderr", "expected_record"),
    [
        ("stdout", subprocess.PIPE, subprocess.DEVNULL, "stdout record"),
        ("stderr", subprocess.DEVNULL, subprocess.PIPE, "stderr record"),
        ("combined", subprocess.PIPE, subprocess.STDOUT, "stdout record"),
    ],
)
def test_run_logged_command_configures_capture_and_streams_before_waiting(
    monkeypatch: pytest.MonkeyPatch,
    capture: commands.CommandLogCapture,
    expected_stdout: int,
    expected_stderr: int,
    expected_record: str,
) -> None:
    process = _FakeProcess()
    captured_popen: dict = {}

    def fake_popen(command, **kwargs):
        captured_popen["command"] = command
        captured_popen.update(kwargs)
        return process

    monkeypatch.setattr(commands.subprocess, "Popen", fake_popen)
    records: list[str] = []

    def on_log(record: str) -> None:
        assert not process.waited
        records.append(record)

    commands.run_logged_command(
        ("tool", "--flag"),
        capture=capture,
        log_prefix="tool",
        fallback_logger=_FakeLogger(),
        on_log=on_log,
    )

    assert records == [expected_record]
    assert process.waited
    assert captured_popen == {
        "command": ["tool", "--flag"],
        "stdin": subprocess.DEVNULL,
        "stdout": expected_stdout,
        "stderr": expected_stderr,
    }


def test_run_logged_command_uses_prefixed_fallback_logger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(stdout=b"first\rsecond\n")
    monkeypatch.setattr(
        commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    fallback_logger = _FakeLogger()

    commands.run_logged_command(
        ["tool"],
        capture="stdout",
        log_prefix="example",
        fallback_logger=fallback_logger,
    )

    assert fallback_logger.records == [
        ("Running %s command: %s", "example", ["tool"]),
        ("%s: %s", "example", "first"),
        ("%s: %s", "example", "second"),
    ]


def test_run_logged_command_logs_output_before_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(2, stderr=b"before failure\n")
    monkeypatch.setattr(
        commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    records: list[str] = []

    with pytest.raises(subprocess.CalledProcessError) as error:
        commands.run_logged_command(
            ["tool", "--fail"],
            capture="stderr",
            log_prefix="tool",
            fallback_logger=_FakeLogger(),
            on_log=records.append,
        )

    assert records == ["before failure"]
    assert error.value.returncode == 2
    assert error.value.cmd == ["tool", "--fail"]


def test_run_logged_command_terminates_when_callback_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess(stdout=b"record\n")
    monkeypatch.setattr(
        commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    def fail_to_log(record: str) -> None:
        raise RuntimeError(f"Could not log: {record}")

    with pytest.raises(RuntimeError, match="Could not log: record"):
        commands.run_logged_command(
            ["tool"],
            capture="combined",
            log_prefix="tool",
            fallback_logger=_FakeLogger(),
            on_log=fail_to_log,
        )

    assert process.terminated
    assert process.waited


def test_run_logged_command_terminates_when_reading_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = _FakeProcess()
    process.stdout = _FailingStream()
    monkeypatch.setattr(
        commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )

    with pytest.raises(OSError, match="Could not read command output"):
        commands.run_logged_command(
            ["tool"],
            capture="stdout",
            log_prefix="tool",
            fallback_logger=_FakeLogger(),
        )

    assert process.terminated
    assert process.waited
