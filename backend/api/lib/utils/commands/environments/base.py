from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from anyio import to_thread

from ..common import CommandLogCapture, CommandTool

type LogCallback = Callable[[str], None]
type CommandLogStream = Literal["stdout", "stderr"]

# How much captured output a CommandExecutionError keeps for diagnostics.
ERROR_LOG_TAIL_RECORDS = 15
ERROR_LOG_RECORD_MAX_LENGTH = 500


@dataclass(frozen=True)
class Command:
    tool: CommandTool
    arguments: tuple[str, ...]
    capture: CommandLogCapture
    # Return codes that succeed although they are not zero, such as spirula
    # sfm's 3 for a partial reconstruction.
    acceptable_return_codes: tuple[int, ...] = ()


@dataclass(frozen=True)
class CommandResult:
    return_code: int


class CommandExecutionError(RuntimeError):
    def __init__(
        self,
        command: Command,
        *,
        return_code: int | None = None,
        message: str | None = None,
        log_tail: Sequence[str] | None = None,
    ) -> None:
        self.command = command
        self.return_code = return_code
        self.log_tail = list(log_tail or ())

        if message is None:
            if return_code is None:
                message = f"Failed to start {command.tool} command"
            else:
                message = (
                    f"{command.tool} command exited with return code {return_code}"
                )
        if self.log_tail:
            message = "\n".join(
                [message, "Last output:"]
                + [f"  {_shorten(record)}" for record in self.log_tail]
            )

        super().__init__(message)


def _shorten(record: str) -> str:
    if len(record) <= ERROR_LOG_RECORD_MAX_LENGTH:
        return record
    return record[: ERROR_LOG_RECORD_MAX_LENGTH - 3] + "..."


class CommandExecutionEnvironment(ABC):
    async def run[T](self, operation: Callable[[], T]) -> T:
        return await to_thread.run_sync(operation)

    @abstractmethod
    def execute(
        self,
        command: Command,
        *,
        workspace: Path,
        on_log: LogCallback | None = None,
    ) -> CommandResult:
        pass
