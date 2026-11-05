import logging
import os
import shutil
import signal
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from anyio import CancelScope, to_thread

from ..common import BinaryReadStream, CommandTool, iter_command_log_records
from .base import (
    ERROR_LOG_TAIL_RECORDS,
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


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    # Descendants can still own the output stream after the leader exits.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


class LocalCommandExecutionEnvironment(CommandExecutionEnvironment):
    def __init__(self, executable_directory: Path = LOCAL_EXECUTABLES_DIRECTORY):
        self.executable_directory = executable_directory
        self._condition = threading.Condition()
        self._cancelled = False
        self._running: set[subprocess.Popen[bytes]] = set()

    async def run[T](self, operation: Callable[[], T]) -> T:
        try:
            return await to_thread.run_sync(operation, abandon_on_cancel=True)
        except BaseException:
            # Cancelling the await does not stop the synchronous output reader.
            # Keep the event loop available until its callbacks have finished.
            with CancelScope(shield=True):
                await to_thread.run_sync(self.cancel)
            raise

    def cancel(self) -> None:
        """Kill command groups and wait for their output handling to finish.

        Call from a worker thread so in-flight callbacks can use the event loop.
        A cancelled environment cannot start another command.
        """
        with self._condition:
            self._cancelled = True
            for process in self._running:
                _kill_process_group(process)
            self._condition.wait_for(lambda: not self._running)

    def _finish_execution(self, process: subprocess.Popen[bytes]) -> None:
        with self._condition:
            self._running.remove(process)
            self._condition.notify_all()

    def _resolve_tool(self, tool: CommandTool) -> str:
        bundled_executable = self.executable_directory / tool
        if bundled_executable.is_file():
            return str(bundled_executable)

        system_executable = shutil.which(tool)
        if system_executable is not None:
            return system_executable

        raise FileNotFoundError(f"{tool} executable was not found")

    def _start_process(
        self,
        command: Command,
        *,
        argv: list[str],
        workspace: Path,
        stdout: int,
        stderr: int,
    ) -> subprocess.Popen[bytes]:
        # Starting and registering must be atomic with respect to cancellation.
        with self._condition:
            if self._cancelled:
                raise CommandExecutionError(
                    command, message="Local command execution was cancelled"
                )
            try:
                process = subprocess.Popen(
                    argv,
                    cwd=workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    bufsize=0,
                    start_new_session=True,
                )
            except OSError as exc:
                raise CommandExecutionError(command, message=str(exc)) from exc
            self._running.add(process)
            return process

    def _consume_output(
        self,
        command: Command,
        process: subprocess.Popen[bytes],
        stream: BinaryReadStream,
        emit_log: LogCallback,
    ) -> CommandResult:
        log_tail: deque[str] = deque(maxlen=ERROR_LOG_TAIL_RECORDS)

        for record in iter_command_log_records(stream):
            with self._condition:
                cancelled = self._cancelled
            if not cancelled:
                log_tail.append(record)
                emit_log(record)

        return_code = process.wait()
        with self._condition:
            if self._cancelled:
                raise CommandExecutionError(
                    command,
                    return_code=return_code,
                    message="Local command execution was cancelled",
                    log_tail=log_tail,
                )
        if return_code != 0 and return_code not in command.acceptable_return_codes:
            raise CommandExecutionError(
                command, return_code=return_code, log_tail=log_tail
            )
        return CommandResult(return_code=return_code)

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

        # Release the execution only after waiting and closing every descriptor.
        with ExitStack() as execution_cleanup, ExitStack() as resources:
            process = self._start_process(
                command,
                argv=argv,
                workspace=workspace,
                stdout=settings.stdout,
                stderr=settings.stderr,
            )

            execution_cleanup.callback(self._finish_execution, process)
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    resources.callback(pipe.close)
            resources.callback(process.wait)

            try:
                with self._condition:
                    cancelled = self._cancelled
                if not cancelled:
                    logger.info("Running %s command: %s", command.tool, argv)
                stream = (
                    process.stdout
                    if settings.log_stream == "stdout"
                    else process.stderr
                )
                if stream is None:
                    raise RuntimeError(f"{settings.log_stream} was not captured")
                return self._consume_output(command, process, stream, emit_log)
            except BaseException:
                _kill_process_group(process)
                raise
