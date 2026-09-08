import io
import logging
import subprocess
from pathlib import Path

import pytest
from api.lib.utils import commands
from api.lib.utils.commands import iter_command_log_records
from api.lib.utils.commands.environments import local as local_commands


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


def test_local_environment_prefers_bundled_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    bundled_ffmpeg = executable_directory / "ffmpeg"
    bundled_ffmpeg.touch()
    monkeypatch.setattr(local_commands.shutil, "which", lambda tool: "/usr/bin/ffmpeg")

    environment = commands.LocalCommandExecutionEnvironment(executable_directory)

    assert environment._resolve_tool("ffmpeg") == str(bundled_ffmpeg)


def test_local_environment_falls_back_to_system_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(local_commands.shutil, "which", lambda tool: "/usr/bin/colmap")
    environment = commands.LocalCommandExecutionEnvironment(tmp_path / "missing")

    assert environment._resolve_tool("colmap") == "/usr/bin/colmap"


@pytest.mark.parametrize(
    ("capture", "expected_stdout", "expected_stderr", "expected_record"),
    [
        ("stdout", subprocess.PIPE, subprocess.DEVNULL, "stdout record"),
        ("stderr", subprocess.DEVNULL, subprocess.PIPE, "stderr record"),
        ("combined", subprocess.PIPE, subprocess.STDOUT, "stdout record"),
    ],
)
def test_local_environment_configures_capture_and_streams_before_waiting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
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

    monkeypatch.setattr(local_commands.subprocess, "Popen", fake_popen)
    environment = commands.LocalCommandExecutionEnvironment()
    monkeypatch.setattr(environment, "_resolve_tool", lambda tool: "/bin/tool")
    records: list[str] = []

    def on_log(record: str) -> None:
        assert not process.waited
        records.append(record)

    result = environment.execute(
        commands.Command(tool="ffmpeg", arguments=("--flag",), capture=capture),
        workspace=tmp_path,
        on_log=on_log,
    )

    assert result == commands.CommandResult(return_code=0)
    assert records == [expected_record]
    assert process.waited
    assert captured_popen == {
        "command": ["/bin/tool", "--flag"],
        "cwd": tmp_path.resolve(),
        "stdin": subprocess.DEVNULL,
        "stdout": expected_stdout,
        "stderr": expected_stderr,
    }


def test_local_environment_uses_prefixed_fallback_logger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _FakeProcess(stdout=b"first\rsecond\n")
    monkeypatch.setattr(
        local_commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    fallback_logger = _FakeLogger()
    monkeypatch.setattr(local_commands, "logger", fallback_logger)
    environment = commands.LocalCommandExecutionEnvironment()
    monkeypatch.setattr(environment, "_resolve_tool", lambda tool: "/bin/tool")

    environment.execute(
        commands.Command(tool="ffmpeg", arguments=(), capture="stdout"),
        workspace=tmp_path,
    )

    assert fallback_logger.records == [
        ("Running %s command: %s", "ffmpeg", ["/bin/tool"]),
        ("%s: %s", "ffmpeg", "first"),
        ("%s: %s", "ffmpeg", "second"),
    ]


def test_local_environment_logs_output_before_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _FakeProcess(2, stderr=b"before failure\n")
    monkeypatch.setattr(
        local_commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    environment = commands.LocalCommandExecutionEnvironment()
    monkeypatch.setattr(environment, "_resolve_tool", lambda tool: "/bin/tool")
    records: list[str] = []
    command = commands.Command(tool="ffmpeg", arguments=("--fail",), capture="stderr")

    with pytest.raises(commands.CommandExecutionError) as error:
        environment.execute(
            command,
            workspace=tmp_path,
            on_log=records.append,
        )

    assert records == ["before failure"]
    assert error.value.return_code == 2
    assert error.value.command == command


def test_local_environment_wraps_process_start_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    environment = commands.LocalCommandExecutionEnvironment()
    command = commands.Command(tool="colmap", arguments=(), capture="combined")

    def missing_tool(tool: commands.CommandTool) -> str:
        raise FileNotFoundError("missing tool")

    monkeypatch.setattr(environment, "_resolve_tool", missing_tool)

    with pytest.raises(commands.CommandExecutionError, match="missing tool") as error:
        environment.execute(command, workspace=tmp_path)

    assert error.value.command == command
    assert error.value.return_code is None


def test_local_environment_terminates_when_callback_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _FakeProcess(stdout=b"record\n")
    monkeypatch.setattr(
        local_commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    environment = commands.LocalCommandExecutionEnvironment()
    monkeypatch.setattr(environment, "_resolve_tool", lambda tool: "/bin/tool")

    def fail_to_log(record: str) -> None:
        raise RuntimeError(f"Could not log: {record}")

    with pytest.raises(RuntimeError, match="Could not log: record"):
        environment.execute(
            commands.Command(tool="ffmpeg", arguments=(), capture="combined"),
            workspace=tmp_path,
            on_log=fail_to_log,
        )

    assert process.terminated
    assert process.waited


def test_local_environment_terminates_when_reading_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    process = _FakeProcess()
    process.stdout = _FailingStream()
    monkeypatch.setattr(
        local_commands.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    environment = commands.LocalCommandExecutionEnvironment()
    monkeypatch.setattr(environment, "_resolve_tool", lambda tool: "/bin/tool")

    with pytest.raises(OSError, match="Could not read command output"):
        environment.execute(
            commands.Command(tool="ffmpeg", arguments=(), capture="stdout"),
            workspace=tmp_path,
        )

    assert process.terminated
    assert process.waited
