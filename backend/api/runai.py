import json
import logging
import os
import secrets
import subprocess
from datetime import datetime
from typing import Literal

from .config import config

logger = logging.getLogger("uvicorn.error")


LOGS_DIR_PATH = "log"
RUNAI_STATUSES_RUNNING = {"Running", "Terminating"}
RUNAI_STATUSES_COMPLETED = {"Completed", "Stopped", "Succeeded"}
RUNAI_STATUSES_FAILED = {
    "Failed",
    "ImagePullBackOff",
    "ErrImagePull",
    "CrashLoopBackOff",
    "OOMKilled",
    "Evicted",
    "Error",
}


def get_log_file_path(job_name: str) -> str:
    """Get the local path to the log file for a given job.

    Args:
        job_name: Name of the Run:AI job.
    Returns:
        Absolute local path to the log file for the job.
    """
    return os.path.join(LOGS_DIR_PATH, f"{job_name}.log")


def copy_data_to_scratch(source_path: str, dest_path: str) -> None:
    """Copy data from a local absolute path to the scratch remote.

    Args:
        source_path: Absolute local path to copy from.
        dest_path: Relative destination path, prepended with the scratch remote.
    """
    full_dest = f"{config.RUNAI_MOUNT_SCRATCH_PATH}/{dest_path.lstrip('/')}"
    logger.info(f"Copying data from {source_path} to {full_dest} using rclone")
    subprocess.run(
        [
            "rclone",
            "copy",
            source_path,
            full_dest,
            "--create-empty-src-dirs",
            "--copy-links",
        ],
        check=True,
    )


def copy_data_from_scratch(source_path: str, dest_path: str) -> None:
    """Copy data from the scratch remote to a local absolute path.

    Args:
        source_path: Relative source path, prepended with the scratch remote.
        dest_path: Absolute local path to copy to.
    """
    full_source = f"{config.RUNAI_MOUNT_SCRATCH_PATH}/{source_path.lstrip('/')}"
    logger.info(f"Copying data from {full_source} to {dest_path} using rclone")
    subprocess.run(
        [
            "rclone",
            "copy",
            full_source,
            dest_path,
            "--create-empty-src-dirs",
            "--copy-links",
        ],
        check=True,
    )


def refresh_logs() -> None:
    """Refresh the local logs directory by copying data from the scratch remote."""
    try:
        copy_data_from_scratch(LOGS_DIR_PATH, LOGS_DIR_PATH)
    except Exception:
        pass


def submit_job(
    tool: Literal["ffmpeg", "colmap", "brush"],
    command: list[str],
    n_gpu: int = 1,
    unbuffer: bool = False,
) -> str:
    hex_suffix = secrets.token_hex(4)
    job_name = f"{tool}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{hex_suffix}"

    logger.info(
        f"Submitting Run:AI job {job_name} with command: {tool} {' '.join(command)}"
    )

    if unbuffer:
        shell_command = (
            "cd /scratch"
            + f" && mkdir -p {LOGS_DIR_PATH}"
            + f' && script -q -e -f -c \\"{" ".join(command)}\\" /dev/null'
            + " | stdbuf -o0 tr \\'\\r\\' \\'\\n\\'"
            + " | stdbuf -o0 tee "
            + os.path.join("/scratch", get_log_file_path(job_name))
        )
    else:
        shell_command = " ".join(
            [
                f"cd /scratch && mkdir -p {LOGS_DIR_PATH} && ",
                *command,
                "2>&1 | tee",
                os.path.join("/scratch", get_log_file_path(job_name)),
            ]
        )

    subprocess.run(
        [
            "runai",
            "submit",
            job_name,
            "--image",
            f"{config.RUNAI_REGISTRY}/hud-{tool}:latest",
            "--gpu",
            str(n_gpu),
            "--existing-pvc",
            f"claimname={config.RUNAI_PVC_SCRATCH_NAME},path=/scratch",
            "--interactive",
            "--command",
            "--",
            "/bin/sh",
            "-c",
            shell_command,
        ],
        check=True,
    )

    return job_name


def get_job_status(job_name: str) -> str | None:
    try:
        result = subprocess.run(
            ["runai", "describe", "job", job_name, "-o", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get job status for {job_name}: {e}")
        return None

    try:
        job_info = json.loads(result.stdout)
        return job_info["status"]

    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to parse job status for {job_name}: {e}")
        return None


def check_job_started(job_name: str) -> bool:
    status = get_job_status(job_name)
    if status is None:
        return False

    return (
        status
        in RUNAI_STATUSES_RUNNING | RUNAI_STATUSES_COMPLETED | RUNAI_STATUSES_FAILED
    )


def check_job_terminated(job_name: str) -> bool | None:
    status = get_job_status(job_name)
    if status is None:
        return None

    return status in RUNAI_STATUSES_COMPLETED | RUNAI_STATUSES_FAILED
