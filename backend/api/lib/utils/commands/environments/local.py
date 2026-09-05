import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..common import CommandTool, iter_command_log_records
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

        try:
            executable = self._resolve_tool(command.tool)
            argv = [executable, *command.arguments]
            logger.info("Running %s command: %s", command.tool, argv)
            process = subprocess.Popen(
                argv,
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=settings.stdout,
                stderr=settings.stderr,
            )
        except OSError as exc:
            raise CommandExecutionError(command, message=str(exc)) from exc

        emit_log = on_log or (
            lambda record: logger.info("%s: %s", command.tool, record)
        )

        try:
            stream = (
                process.stdout if settings.log_stream == "stdout" else process.stderr
            )
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
            raise CommandExecutionError(command, return_code=return_code)

        return CommandResult(return_code=return_code)
