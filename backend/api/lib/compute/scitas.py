import logging
import os
import posixpath
import secrets
import shlex
import subprocess
import threading
from datetime import datetime

import paramiko
from api.config import config
from api.lib.compute.remote import RemoteCompute, StepName

logger = logging.getLogger("uvicorn.error")

LOGS_DIR_PATH = "log"

# Persistent SSH client ---------------------------------------------------
_ssh_client: paramiko.SSHClient | None = None
_ssh_lock = threading.Lock()

# Cache mapping from our job_name to Slurm JobID (for faster lookups)
_job_id_cache: dict[str, str] = {}

# SLURM job-state groups --------------------------------------------------
SLURM_STATES_PENDING = {
    "PENDING",
    "CONFIGURING",
    "REQUEUE_FED",
    "REQUEUE_HOLD",
    "REQUEUED",
    "SPECIAL_EXIT",
    "STAGE_IN",
}
SLURM_STATES_RUNNING = {"RUNNING", "COMPLETING", "STAGE_OUT", "RESIZING", "SUSPENDED"}
SLURM_STATES_COMPLETED = {
    "COMPLETED",
    "CANCELLED",
    "FAILED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
    "NODE_FAIL",
}
SLURM_STATES_FAILED = {
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "BOOT_FAIL",
    "DEADLINE",
    "NODE_FAIL",
    "PREEMPTED",
}


def _get_ssh_client() -> paramiko.SSHClient:
    """Return an active SSH client, reconnecting if necessary."""
    global _ssh_client

    with _ssh_lock:
        if _ssh_client is not None:
            transport = _ssh_client.get_transport()
            if transport is not None and transport.is_active():
                return _ssh_client
            try:
                _ssh_client.close()
            except Exception:
                pass
            _ssh_client = None

        _ssh_client = paramiko.SSHClient()
        _ssh_client.load_system_host_keys()
        _ssh_client.set_missing_host_key_policy(paramiko.WarningPolicy())

        key_path = os.path.expanduser(config.SCITAS_SSH_KEY_PATH)
        connect_kwargs: dict = {
            "hostname": config.SCITAS_HOST,
            "username": config.SCITAS_SSH_USERNAME,
            "look_for_keys": False,
            "allow_agent": False,
        }

        if key_path and os.path.exists(key_path):
            connect_kwargs["key_filename"] = key_path
        else:
            logger.warning(
                f"SSH key not found at {key_path}, falling back to default key search"
            )
            connect_kwargs["look_for_keys"] = True

        _ssh_client.connect(**connect_kwargs)
        logger.info(f"Connected to Scitas SSH at {config.SCITAS_HOST}")
        return _ssh_client


def _exec_ssh_command(command: str) -> tuple[str, str, int]:
    """Execute a command on the Scitas login node via the persistent SSH connection.

    Returns:
        (stdout, stderr, return_code)
    """
    client = _get_ssh_client()
    stdin, stdout, stderr = client.exec_command(command, get_pty=False)
    exit_status = stdout.channel.recv_exit_status()
    out = stdout.read().decode("utf-8", errors="replace").strip()
    err = stderr.read().decode("utf-8", errors="replace").strip()
    return out, err, exit_status


def _get_slurm_job_id(job_name: str) -> str | None:
    """Resolve our job_name to a Slurm JobID (cached, or looked up via sacct)."""
    if job_name in _job_id_cache:
        return _job_id_cache[job_name]

    out, _, rc = _exec_ssh_command(
        f"sacct -n -P -o JobID --name {shlex.quote(job_name)} | head -n 1"
    )
    if rc == 0 and out.strip():
        job_id = out.strip()
        _job_id_cache[job_name] = job_id
        return job_id

    return None


class Scitas(RemoteCompute):
    @staticmethod
    def get_log_file_path(job_name: str) -> str:
        """Return the local path to the log file for a given job.

        Logs are written to the export file system, which is locally mounted
        at ``SCITAS_MOUNT_EXPORT_PATH``.
        """
        return os.path.join(
            config.SCITAS_MOUNT_EXPORT_PATH, LOGS_DIR_PATH, f"{job_name}.log"
        )

    @staticmethod
    def copy_data_to_scratch(source_path: str, dest_path: str) -> None:
        """Copy data from a local absolute path to the Scitas export (mount).

        The export path is locally mounted on the backend, so ``rsync`` is
        used directly.  The compute job will later rsync the data from the
        remote export path to scratch before execution.
        """
        full_dest = os.path.join(config.SCITAS_MOUNT_EXPORT_PATH, dest_path.lstrip("/"))
        os.makedirs(full_dest, exist_ok=True)
        logger.info(f"Copying data from {source_path} to {full_dest} using rsync")
        subprocess.run(
            [
                "rsync",
                "-a",
                "--no-owner",
                "--no-group",
                "--ignore-existing",
                f"{source_path}/",
                f"{full_dest}/",
            ],
            check=True,
            capture_output=True,
            timeout=3600,
        )

    @staticmethod
    def copy_data_from_scratch(source_path: str, dest_path: str) -> None:
        """Copy data from the Scitas export (mount) to a local absolute path.

        The export path is locally mounted on the backend, so ``rsync`` is
        used directly.  The compute job copies results back to export before
        this method is called.
        """
        full_source = os.path.join(
            config.SCITAS_MOUNT_EXPORT_PATH, source_path.lstrip("/")
        )
        os.makedirs(dest_path, exist_ok=True)
        logger.info(f"Copying data from {full_source} to {dest_path} using rsync")
        subprocess.run(
            [
                "rsync",
                "-a",
                "--no-owner",
                "--no-group",
                "--ignore-existing",
                f"{full_source}/",
                f"{dest_path}/",
            ],
            check=True,
            capture_output=True,
            timeout=3600,
        )

    @staticmethod
    def refresh_logs() -> None:
        """No-op: logs live on the locally-mounted export path."""
        pass

    @staticmethod
    def submit_job(
        tool: StepName,
        command: list[str],
        n_gpu: int = 1,
        workspace_rel_path: str | None = None,
    ) -> str:
        """Submit a Slurm batch job via SSH and return our internal job name."""
        hex_suffix = secrets.token_hex(4)
        job_name = f"{tool}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{hex_suffix}"

        export_root = config.SCITAS_REMOTE_EXPORT_PATH
        scratch_root = config.SCITAS_REMOTE_SCRATCH_PATH
        image_name = posixpath.join(
            config.SCITAS_REMOTE_IMAGES_PATH, f"hud-{tool}_latest.sif"
        )

        log_file_abs = posixpath.join(export_root, LOGS_DIR_PATH, f"{job_name}.log")
        shell_cmd = " ".join(shlex.quote(arg) for arg in command)
        account_line = (
            f"#SBATCH --account={config.SCITAS_ACCOUNT}\n"
            if config.SCITAS_ACCOUNT
            else ""
        )

        batch_script = f"""#!/bin/bash
#SBATCH --job-name={job_name}
{account_line}#SBATCH --partition={"l40s" if tool == "brush" else "mig24gb"}
#SBATCH --gpus={n_gpu}
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=5
#SBATCH --mem=28G
#SBATCH --time=12:00:00
#SBATCH --output={log_file_abs}
#SBATCH --error={log_file_abs}
{config.SCITAS_SBATCH_ARGS_BRUSH if tool == "brush" else config.SCITAS_SBATCH_ARGS_COLMAP}
"""

        if workspace_rel_path:
            workspace_rel = workspace_rel_path.lstrip("/")
            batch_script += f"""
set -e
EXPORT_ROOT={shlex.quote(export_root)}
SCRATCH_ROOT={shlex.quote(scratch_root)}
WORKSPACE_REL={shlex.quote(workspace_rel)}
EXPORT_DIR="$EXPORT_ROOT/$WORKSPACE_REL"
SCRATCH_DIR="$SCRATCH_ROOT/$WORKSPACE_REL"
mkdir -p "$SCRATCH_DIR"
mkdir -p "$(dirname {shlex.quote(log_file_abs)})"

# Stage-in: copy data from export to scratch
rsync -av --ignore-existing "$EXPORT_DIR/" "$SCRATCH_DIR/"

cd "$SCRATCH_ROOT" || cd "$HOME"

# Run inside apptainer with GPU support
apptainer exec --nv {shlex.quote(image_name)} {shell_cmd}

# Stage-out: copy results back to export
rsync -av --ignore-existing "$SCRATCH_DIR/" "$EXPORT_DIR/"
"""
        else:
            batch_script += f"""
cd "$SCRATCH_ROOT" || cd "$HOME"
apptainer exec --nv {shlex.quote(image_name)} {shell_cmd}
"""

        remote_script = posixpath.join("/tmp", f"scitas_{job_name}.sh")
        client = _get_ssh_client()
        stdin, stdout, stderr = client.exec_command(
            f"cat > {shlex.quote(remote_script)}", get_pty=False
        )
        stdin.write(batch_script)
        stdin.close()

        exit_status = stdout.channel.recv_exit_status()
        err = stderr.read().decode("utf-8", errors="replace").strip()
        if exit_status != 0:
            raise RuntimeError(f"Failed to write remote batch script: {err}")

        # Submit the job with sbatch
        out, err, rc = _exec_ssh_command(
            f"sbatch --parsable {shlex.quote(remote_script)}"
        )
        if rc != 0:
            raise RuntimeError(f"sbatch failed: {err}")

        job_id = out.strip().partition(";")[0]
        if not job_id:
            raise RuntimeError("sbatch did not return a JobID")

        _job_id_cache[job_name] = job_id
        logger.info(f"Submitted Scitas job {job_name} (Slurm ID {job_id})")

        # Clean up the remote temporary script
        _exec_ssh_command(f"rm -f {shlex.quote(remote_script)}")

        return job_name

    @staticmethod
    def get_job_status(job_name: str) -> str | None:
        """Query the current Slurm state for the given job."""
        job_id = _get_slurm_job_id(job_name)
        if job_id is None:
            return None

        # Running / pending jobs are visible in squeue
        out, _, rc = _exec_ssh_command(f"squeue -j {shlex.quote(job_id)} -h -o '%T'")
        if rc == 0 and out:
            return out.strip()

        # Job has left the queue – look up its final state in sacct
        out, _, rc = _exec_ssh_command(
            f"sacct -j {shlex.quote(job_id)} -n -P -o State | head -n 1"
        )
        if rc == 0 and out:
            return out.strip()

        return None

    @staticmethod
    def check_job_started(job_name: str) -> bool:
        """Return True once the job has been submitted and is known to Slurm."""
        return Scitas.get_job_status(job_name) is not None

    @staticmethod
    def check_job_terminated(job_name: str) -> bool | None:
        """Return True if the job has finished, False if still running, None if unknown."""
        status = Scitas.get_job_status(job_name)
        if status is None:
            return None
        return status in SLURM_STATES_COMPLETED
