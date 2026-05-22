from abc import ABC, abstractmethod
from typing import Literal

StepName = Literal["ffmpeg", "colmap", "brush"]


class RemoteCompute(ABC):
    """Interface for remote compute resources."""

    @staticmethod
    @abstractmethod
    def get_log_file_path(job_name: str) -> str:
        pass

    @staticmethod
    @abstractmethod
    def copy_data_to_scratch(source_path: str, dest_path: str) -> None:
        pass

    @staticmethod
    @abstractmethod
    def copy_data_from_scratch(source_path: str, dest_path: str) -> None:
        pass

    @staticmethod
    @abstractmethod
    def refresh_logs() -> None:
        pass

    @staticmethod
    @abstractmethod
    def submit_job(
        tool: StepName,
        command: list[str],
        n_gpu: int = 1,
    ) -> str:
        pass

    @staticmethod
    @abstractmethod
    def get_job_status(job_name: str) -> str | None:
        pass

    @staticmethod
    @abstractmethod
    def check_job_started(job_name: str) -> bool:
        pass

    @staticmethod
    @abstractmethod
    def check_job_terminated(job_name: str) -> bool | None:
        pass
