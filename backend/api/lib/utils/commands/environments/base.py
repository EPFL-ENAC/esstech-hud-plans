from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from ..common import CommandTool

type LogCallback = Callable[[str], None]
type CommandLogCapture = Literal["stdout", "stderr", "combined"]
type CommandLogStream = Literal["stdout", "stderr"]


@dataclass(frozen=True)
class Command:
    tool: CommandTool
    arguments: tuple[str, ...]
    capture: CommandLogCapture


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
    ) -> None:
        self.command = command
        self.return_code = return_code

        if message is None:
            if return_code is None:
                message = f"Failed to start {command.tool} command"
            else:
                message = (
                    f"{command.tool} command exited with return code {return_code}"
                )

        super().__init__(message)


class CommandExecutionEnvironment(ABC):
    @abstractmethod
    def execute(
        self,
        command: Command,
        *,
        workspace: Path,
        on_log: LogCallback | None = None,
    ) -> CommandResult:
        pass
