import codecs
import logging
import time
from pathlib import Path, PurePosixPath
from typing import Callable

from api.lib.compute.scitas import (
    SLURM_STATES_COMPLETED,
    Scitas,
    ScitasJobResult,
)

from .base import (
    Command,
    CommandExecutionEnvironment,
    CommandExecutionError,
    CommandResult,
    LogCallback,
)

logger = logging.getLogger(__name__)


class _IncrementalLogTail:
    def __init__(self) -> None:
        self.position = 0
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.record_parts: list[str] = []

    def _consume(self, text: str, emit: Callable[[str], None]) -> None:
        for character in text:
            if character in "\r\n":
                record = "".join(self.record_parts).rstrip()
                self.record_parts.clear()
                if record:
                    emit(record)
            else:
                self.record_parts.append(character)

    def read(self, path: Path, emit: Callable[[str], None]) -> None:
        try:
            with path.open("rb") as stream:
                stream.seek(self.position)
                chunk = stream.read()
                self.position = stream.tell()
        except FileNotFoundError:
            return

        if chunk:
            self._consume(self.decoder.decode(chunk), emit)

    def finish(self, emit: Callable[[str], None]) -> None:
        self._consume(self.decoder.decode(b"", final=True), emit)
        final_record = "".join(self.record_parts).rstrip()
        self.record_parts.clear()
        if final_record:
            emit(final_record)


class ScitasCommandExecutionEnvironment(CommandExecutionEnvironment):
    def __init__(
        self,
        *,
        poll_interval_seconds: float = 5,
        max_status_failures: int = 5,
        remote_workspace_prefix: PurePosixPath = PurePosixPath("workflows"),
    ) -> None:
        if poll_interval_seconds < 0:
            raise ValueError("poll_interval_seconds must not be negative")
        if max_status_failures < 1:
            raise ValueError("max_status_failures must be at least 1")
        if (
            remote_workspace_prefix.is_absolute()
            or ".." in remote_workspace_prefix.parts
        ):
            raise ValueError("remote_workspace_prefix must be a safe relative path")

        self.poll_interval_seconds = poll_interval_seconds
        self.max_status_failures = max_status_failures
        self.remote_workspace_prefix = remote_workspace_prefix

    def _remote_workspace(self, workspace: Path) -> str:
        if not workspace.name:
            raise ValueError("Command workspace must have a directory name")
        return (self.remote_workspace_prefix / workspace.name).as_posix()

    def _wait_for_result(
        self,
        command: Command,
        job_name: str,
        on_log: Callable[[str], None],
    ) -> ScitasJobResult:
        log_path = Path(Scitas.get_log_file_path(job_name))
        log_tail = _IncrementalLogTail()
        status_failures = 0

        while True:
            Scitas.refresh_logs()
            log_tail.read(log_path, on_log)
            status = Scitas.get_job_status(job_name)

            if status is None:
                status_failures += 1
            elif status in SLURM_STATES_COMPLETED:
                result = Scitas.get_job_result(job_name)
                if result is not None:
                    Scitas.refresh_logs()
                    log_tail.read(log_path, on_log)
                    log_tail.finish(on_log)
                    return result
                status_failures += 1
            else:
                status_failures = 0

            if status_failures >= self.max_status_failures:
                raise CommandExecutionError(
                    command,
                    message=(
                        "Failed to get Scitas job status after "
                        f"{self.max_status_failures} attempts"
                    ),
                )

            time.sleep(self.poll_interval_seconds)

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

        remote_workspace = self._remote_workspace(workspace)
        emit_log = on_log or (
            lambda record: logger.info("%s: %s", command.tool, record)
        )
        job_name: str | None = None
        job_finished = False

        try:
            Scitas.copy_data_to_scratch(str(workspace), remote_workspace)
            launchers = {
                "ffmpeg": ["ffmpeg"],
                "colmap": ["xvfb-run", "-a", "colmap"],
                "brush": ["brush"],
            }
            argv = [*launchers[command.tool], *command.arguments]
            job_name = Scitas.submit_job(
                tool=command.tool,
                command=argv,
                workspace_rel_path=remote_workspace,
                working_directory_rel_path=remote_workspace,
                capture=command.capture,
            )
            result = self._wait_for_result(command, job_name, emit_log)
            job_finished = True
        except BaseException:
            if job_name is not None and not job_finished:
                try:
                    Scitas.cancel_job(job_name)
                except Exception:
                    logger.exception("Failed to cancel Scitas job %s", job_name)
            raise

        Scitas.copy_data_from_scratch(remote_workspace, str(workspace))
        if result.return_code != 0:
            raise CommandExecutionError(command, return_code=result.return_code)

        return CommandResult(return_code=0)
