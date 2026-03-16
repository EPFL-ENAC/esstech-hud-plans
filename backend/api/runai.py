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


def check_job_terminated(job_name: str) -> bool:
    status = get_job_status(job_name)
    if status is None:
        return False

    return status in {"Completed", "Failed", "Stopped", "Succeeded"}


# def get_access_token() -> str:
#     url = f"{config.RUNAI_API_URL}/token"
#     header = {
#         "Accept": "*/*",
#         "Content-Type": "application/json",
#     }
#     body = json.dumps(
#         {
#             "grantType": "app_token",
#             "AppId": config.RUNAI_CLIENT_ID,
#             "AppSecret": config.RUNAI_CLIENT_SECRET,
#         }
#     )
#     response = requests.request("POST", url, data=body, headers=header)
#     response.raise_for_status()

#     access_token = response.json().get("accessToken")
#     return access_token


# def submit_job(access_token: str, job_name: str, image: str, n_gpu: int = 1) -> dict:
#     """Submit a training workload to the Run:AI cluster.

#     Args:
#         access_token: Bearer token for authentication.
#         job_name: Name of the job to submit.
#         image: Docker image to use for the job.
#         gpu: Number of GPUs to allocate (default: 1).

#     Returns:
#         The JSON response from the Run:AI API.
#     """
#     # url = f"{config.RUNAI_CLUSTER_URL}/apis/run.ai/v2alpha1/namespaces/{config.RUNAI_PROJECT}/trainingworkloads"
#     # url = f"{config.RUNAI_CLUSTER_URL}/api/v1/workloads/namespaces/{config.RUNAI_PROJECT}/workloads/interactive"
#     url = f"{config.RUNAI_CLUSTER_URL}/apis/run.ai/v2alpha1/namespaces/{config.RUNAI_PROJECT}/interactiveworkloads"
#     headers = {
#         "Content-Type": "application/yaml",
#         "Authorization": f"Bearer {access_token}",
#     }
#     body = json.dumps(
#         {
#             "apiVersion": "run.ai/v2alpha1",
#             "kind": "TrainingWorkload",
#             "metadata": {"name": job_name, "namespace": config.RUNAI_PROJECT},
#             "spec": {
#                 "image": {"value": image},
#                 "name": {"value": job_name},
#                 "gpu": {"value": str(n_gpu)},
#             },
#         }
#     )
#     response = requests.post(url, data=body, headers=headers, verify=False)
#     response.raise_for_status()
#     return response.json()
