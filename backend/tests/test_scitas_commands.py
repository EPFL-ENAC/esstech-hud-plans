from pathlib import Path, PurePosixPath

import pytest
from api.lib.compute import scitas as scitas_compute
from api.lib.utils import commands
from api.lib.utils.commands.environments import scitas as scitas_commands


def test_scitas_environment_stages_runs_streams_and_retrieves_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    log_path = tmp_path / "job.log"
    calls: list[tuple] = []
    status_checks = 0

    def copy_to(source_path: str, dest_path: str) -> None:
        calls.append(("copy-to", source_path, dest_path))

    def submit_job(**kwargs) -> str:
        calls.append(("submit", kwargs))
        return "job-1"

    def get_status(job_name: str) -> str:
        nonlocal status_checks
        assert job_name == "job-1"
        status_checks += 1
        if status_checks == 1:
            log_path.write_bytes(b"first\rpartial \xe2")
            return "RUNNING"
        with log_path.open("ab") as stream:
            stream.write(b"\x98\x83 record\nlast")
        return "COMPLETED"

    def copy_from(source_path: str, dest_path: str) -> None:
        calls.append(("copy-from", source_path, dest_path))

    monkeypatch.setattr(scitas_commands.Scitas, "copy_data_to_scratch", copy_to)
    monkeypatch.setattr(scitas_commands.Scitas, "submit_job", submit_job)
    monkeypatch.setattr(
        scitas_commands.Scitas,
        "get_log_file_path",
        lambda job_name: str(log_path),
    )
    monkeypatch.setattr(scitas_commands.Scitas, "refresh_logs", lambda: None)
    monkeypatch.setattr(scitas_commands.Scitas, "get_job_status", get_status)
    monkeypatch.setattr(
        scitas_commands.Scitas,
        "get_job_result",
        lambda job_name: scitas_compute.ScitasJobResult("COMPLETED", 0),
    )
    monkeypatch.setattr(scitas_commands.Scitas, "copy_data_from_scratch", copy_from)
    sleeps: list[float] = []
    monkeypatch.setattr(scitas_commands.time, "sleep", sleeps.append)

    environment = commands.ScitasCommandExecutionEnvironment(
        poll_interval_seconds=0.25,
        remote_workspace_prefix=PurePosixPath("remote jobs"),
    )
    command = commands.Command(
        tool="colmap",
        arguments=("--image_path", "frames directory"),
        capture="combined",
    )
    records: list[str] = []

    result = environment.execute(command, workspace=workspace, on_log=records.append)

    remote_workspace = "remote jobs/workspace with spaces"
    assert result == commands.CommandResult(return_code=0)
    assert records == ["first", "partial ☃ record", "last"]
    assert sleeps == [0.25]
    assert calls == [
        ("copy-to", str(workspace.resolve()), remote_workspace),
        (
            "submit",
            {
                "tool": "colmap",
                "command": [
                    "xvfb-run",
                    "-a",
                    "colmap",
                    "--image_path",
                    "frames directory",
                ],
                "workspace_rel_path": remote_workspace,
                "working_directory_rel_path": remote_workspace,
                "capture": "combined",
            },
        ),
        ("copy-from", remote_workspace, str(workspace.resolve())),
    ]


def test_scitas_environment_retrieves_outputs_before_reporting_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    copied_from: list[tuple[str, str]] = []
    cancelled: list[str] = []

    monkeypatch.setattr(
        scitas_commands.Scitas, "copy_data_to_scratch", lambda *args: None
    )
    monkeypatch.setattr(
        scitas_commands.Scitas, "submit_job", lambda **kwargs: "failed-job"
    )
    monkeypatch.setattr(
        scitas_commands.Scitas,
        "get_log_file_path",
        lambda job_name: str(tmp_path / "missing.log"),
    )
    monkeypatch.setattr(scitas_commands.Scitas, "refresh_logs", lambda: None)
    monkeypatch.setattr(
        scitas_commands.Scitas, "get_job_status", lambda job_name: "FAILED"
    )
    monkeypatch.setattr(
        scitas_commands.Scitas,
        "get_job_result",
        lambda job_name: scitas_compute.ScitasJobResult("FAILED", 42),
    )
    monkeypatch.setattr(
        scitas_commands.Scitas,
        "copy_data_from_scratch",
        lambda source, destination: copied_from.append((source, destination)),
    )
    monkeypatch.setattr(scitas_commands.Scitas, "cancel_job", cancelled.append)

    command = commands.Command(tool="colmap", arguments=(), capture="combined")
    environment = commands.ScitasCommandExecutionEnvironment(poll_interval_seconds=0)

    with pytest.raises(commands.CommandExecutionError) as error:
        environment.execute(command, workspace=workspace)

    assert error.value.command == command
    assert error.value.return_code == 42
    assert copied_from == [("workflows/workspace", str(workspace.resolve()))]
    assert cancelled == []


def test_scitas_environment_cancels_job_when_log_callback_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log_path = tmp_path / "job.log"
    log_path.write_text("record\n")
    cancelled: list[str] = []

    monkeypatch.setattr(
        scitas_commands.Scitas, "copy_data_to_scratch", lambda *args: None
    )
    monkeypatch.setattr(
        scitas_commands.Scitas, "submit_job", lambda **kwargs: "running-job"
    )
    monkeypatch.setattr(
        scitas_commands.Scitas,
        "get_log_file_path",
        lambda job_name: str(log_path),
    )
    monkeypatch.setattr(scitas_commands.Scitas, "refresh_logs", lambda: None)
    monkeypatch.setattr(scitas_commands.Scitas, "cancel_job", cancelled.append)

    def fail_to_log(record: str) -> None:
        raise RuntimeError(f"Could not log: {record}")

    environment = commands.ScitasCommandExecutionEnvironment(poll_interval_seconds=0)

    with pytest.raises(RuntimeError, match="Could not log: record"):
        environment.execute(
            commands.Command(tool="colmap", arguments=(), capture="combined"),
            workspace=workspace,
            on_log=fail_to_log,
        )

    assert cancelled == ["running-job"]


def test_scitas_environment_stops_after_unavailable_status_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cancelled: list[str] = []

    monkeypatch.setattr(
        scitas_commands.Scitas, "copy_data_to_scratch", lambda *args: None
    )
    monkeypatch.setattr(
        scitas_commands.Scitas, "submit_job", lambda **kwargs: "unknown-job"
    )
    monkeypatch.setattr(
        scitas_commands.Scitas,
        "get_log_file_path",
        lambda job_name: str(tmp_path / "missing.log"),
    )
    monkeypatch.setattr(scitas_commands.Scitas, "refresh_logs", lambda: None)
    monkeypatch.setattr(scitas_commands.Scitas, "get_job_status", lambda job_name: None)
    monkeypatch.setattr(scitas_commands.Scitas, "cancel_job", cancelled.append)
    monkeypatch.setattr(scitas_commands.time, "sleep", lambda seconds: None)

    environment = commands.ScitasCommandExecutionEnvironment(
        poll_interval_seconds=0,
        max_status_failures=2,
    )

    with pytest.raises(
        commands.CommandExecutionError,
        match="Failed to get Scitas job status after 2 attempts",
    ):
        environment.execute(
            commands.Command(tool="colmap", arguments=(), capture="combined"),
            workspace=workspace,
        )

    assert cancelled == ["unknown-job"]


@pytest.mark.parametrize(
    ("slurm_output", "expected_result"),
    [
        ("COMPLETED|0:0", scitas_compute.ScitasJobResult("COMPLETED", 0)),
        ("FAILED|42:0", scitas_compute.ScitasJobResult("FAILED", 42)),
        ("CANCELLED by 123|0:15", scitas_compute.ScitasJobResult("CANCELLED", 143)),
    ],
)
def test_scitas_job_result_parses_slurm_state_and_exit_code(
    monkeypatch: pytest.MonkeyPatch,
    slurm_output: str,
    expected_result: scitas_compute.ScitasJobResult,
) -> None:
    monkeypatch.setitem(scitas_compute._job_id_cache, "job-1", "123")
    monkeypatch.setattr(
        scitas_compute,
        "_exec_ssh_command",
        lambda command: (slurm_output, "", 0),
    )

    assert scitas_compute.Scitas.get_job_result("job-1") == expected_result


def test_scitas_submit_job_uses_workspace_cwd_capture_and_failure_safe_stage_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    written_scripts: list[str] = []

    class FakeChannel:
        def recv_exit_status(self) -> int:
            return 0

    class FakeOutput:
        channel = FakeChannel()

        def read(self) -> bytes:
            return b""

    class FakeInput:
        def write(self, value: str) -> None:
            written_scripts.append(value)

        def close(self) -> None:
            pass

    class FakeClient:
        def exec_command(self, command: str, get_pty: bool):
            return FakeInput(), FakeOutput(), FakeOutput()

    monkeypatch.setattr(
        scitas_compute.config, "SCITAS_MOUNT_EXPORT_PATH", str(tmp_path)
    )
    monkeypatch.setattr(scitas_compute, "_get_ssh_client", lambda: FakeClient())

    def execute(command: str) -> tuple[str, str, int]:
        if command.startswith("sbatch"):
            return "123", "", 0
        return "", "", 0

    monkeypatch.setattr(scitas_compute, "_exec_ssh_command", execute)
    monkeypatch.setattr(scitas_compute.secrets, "token_hex", lambda size: "abcd1234")

    scitas_compute.Scitas.submit_job(
        tool="colmap",
        command=["colmap", "--image_path", "frames directory"],
        workspace_rel_path="workflows/job",
        working_directory_rel_path="workflows/job",
        capture="stderr",
    )

    assert len(written_scripts) == 1
    script = written_scripts[0]
    expected_log = f"{scitas_compute.config.SCITAS_REMOTE_EXPORT_PATH}/log/"
    assert "#SBATCH --output=/dev/null" in script
    assert f"#SBATCH --error={expected_log}" in script
    assert "WORKING_DIRECTORY_REL=workflows/job" in script
    assert 'cd "$WORKING_DIR"' in script
    assert "colmap --image_path 'frames directory'" in script
    assert "COMMAND_EXIT_CODE=$?" in script
    assert 'rsync -avL --ignore-existing "$SCRATCH_DIR/" "$EXPORT_DIR/"' in script
    assert 'if [ "$COMMAND_EXIT_CODE" -ne 0 ]; then' in script
    assert 'exit "$STAGE_OUT_EXIT_CODE"' in script
