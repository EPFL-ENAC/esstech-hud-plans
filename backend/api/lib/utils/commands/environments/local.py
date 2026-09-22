import errno
import logging
import os
import pty
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..common import BinaryReadStream, CommandTool, iter_command_log_records
from .base import (
    Command,
    CommandExecutionEnvironment,
    CommandExecutionError,
    CommandLogCapture,
    CommandLogStream,
    CommandResult,
    LogCallback,
)

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[5]
LOCAL_EXECUTABLES_DIRECTORY = BACKEND_ROOT / "external" / "bin"


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


class _PtyStream:
    def __init__(self, descriptor: int):
        self.descriptor = descriptor

    def read(self, size: int = -1, /) -> bytes:
        try:
            return os.read(self.descriptor, size if size >= 0 else 4096)
        except OSError as exc:
            # Linux PTYs report EIO when the child closes the slave.
            if exc.errno == errno.EIO:
                return b""
            raise


def _consume_output(
    command: Command,
    process: subprocess.Popen,
    stream: BinaryReadStream,
    emit_log: LogCallback,
) -> CommandResult:
    try:
        for record in iter_command_log_records(stream):
            emit_log(record)
    except BaseException:
        if process.poll() is None:
            process.terminate()
        process.wait()
        raise

    return_code = process.wait()
    if return_code != 0:
        raise CommandExecutionError(command, return_code=return_code)
    return CommandResult(return_code=return_code)


class LocalCommandExecutionEnvironment(CommandExecutionEnvironment):
    def __init__(self, executable_directory: Path = LOCAL_EXECUTABLES_DIRECTORY):
        self.executable_directory = executable_directory

    def _resolve_tool(self, tool: CommandTool) -> str:
        bundled_executable = self.executable_directory / tool
        if bundled_executable.is_file():
            return str(bundled_executable)

        system_executable = shutil.which(tool)
        if system_executable is not None:
            return system_executable

        raise FileNotFoundError(f"{tool} executable was not found")

    def _execute_with_pty(
        self,
        command: Command,
        *,
        argv: list[str],
        workspace: Path,
        emit_log: LogCallback,
    ) -> CommandResult:
        """Brush's progress display needs a terminal, including in headless runs."""
        try:
            master, slave = pty.openpty()
        except OSError as exc:
            raise CommandExecutionError(command, message=str(exc)) from exc

        try:
            child_environment = {**os.environ, "TERM": "xterm-256color"}
            child_environment.pop("NO_COLOR", None)
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=slave if command.capture != "stderr" else subprocess.DEVNULL,
                    stderr=slave if command.capture != "stdout" else subprocess.DEVNULL,
                    env=child_environment,
                    bufsize=0,
                )
            except OSError as exc:
                raise CommandExecutionError(command, message=str(exc)) from exc
            finally:
                os.close(slave)

            return _consume_output(command, process, _PtyStream(master), emit_log)
        finally:
            os.close(master)

    def execute(
        self,
        command: Command,
        *,
        workspace: Path,
        on_log: LogCallback | None = None,
    ) -> CommandResult:
        workspace = workspace.resolve()
        if not workspace.is_dir():
            raise CommandExecutionError(
                command,
                message=f"Command workspace does not exist: {workspace}",
            )

        settings = _COMMAND_SETTINGS.get(command.capture)
        if settings is None:
            raise ValueError(f"Unsupported command log capture mode: {command.capture}")

        emit_log = on_log or (
            lambda record: logger.info("%s: %s", command.tool, record)
        )
        try:
            executable = self._resolve_tool(command.tool)
        except OSError as exc:
            raise CommandExecutionError(command, message=str(exc)) from exc
        argv = [executable, *command.arguments]
        logger.info("Running %s command: %s", command.tool, argv)
        if command.tool == "brush":
            return self._execute_with_pty(
                command, argv=argv, workspace=workspace, emit_log=emit_log
            )

        try:
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=settings.stdout,
                stderr=settings.stderr,
                bufsize=0,
            )
        except OSError as exc:
            raise CommandExecutionError(command, message=str(exc)) from exc

        try:
            stream = (
                process.stdout if settings.log_stream == "stdout" else process.stderr
            )
            if stream is None:
                if process.poll() is None:
                    process.terminate()
                process.wait()
                raise RuntimeError(f"{settings.log_stream} was not captured")
            return _consume_output(command, process, stream, emit_log)
        finally:
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
