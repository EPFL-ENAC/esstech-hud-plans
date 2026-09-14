from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest
from api.lib.compute import scitas as scitas_compute
from api.lib.utils import commands
from api.lib.utils.commands.environments import scitas as scitas_commands


def _stub_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Stub the registry writes and collect the register and forget calls."""
    registered: list[tuple[str, str]] = []
    forgotten: list[tuple[str, str]] = []
    monkeypatch.setattr(
        scitas_compute,
        "register_job",
        lambda job_name, workspace_name: registered.append((job_name, workspace_name)),
    )
    monkeypatch.setattr(
        scitas_compute,
        "forget_job",
        lambda job_name, workspace_name: forgotten.append((job_name, workspace_name)),
    )
    return registered, forgotten


def test_scitas_environment_stages_runs_streams_and_retrieves_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    log_path = tmp_path / "job.log"
    calls: list[tuple] = []
    status_checks = 0
    registered, forgotten = _stub_registry(monkeypatch)

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
    assert registered == [("job-1", "workspace with spaces")]
    assert forgotten == [("job-1", "workspace with spaces")]
    # The executor submits the job and waits for it. The data copies of the
    # workspace belong to the pipeline, not to the executor.
    assert calls == [
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
    registered, forgotten = _stub_registry(monkeypatch)

    command = commands.Command(tool="colmap", arguments=(), capture="combined")
    environment = commands.ScitasCommandExecutionEnvironment(poll_interval_seconds=0)

    with pytest.raises(commands.CommandExecutionError) as error:
        environment.execute(command, workspace=workspace)

    assert error.value.command == command
    assert error.value.return_code == 42
    # The executor does not copy the workspace data. The pipeline does.
    assert copied_from == []
    assert cancelled == []
    assert registered == [("failed-job", "workspace")]
    # A job that reports failure in a normal way is dropped from the registry.
    assert forgotten == [("failed-job", "workspace")]


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
    registered, forgotten = _stub_registry(monkeypatch)

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
    assert registered == [("running-job", "workspace")]
    # The cancellation path runs, so the executor drops the job entry.
    assert forgotten == [("running-job", "workspace")]


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
    registered, forgotten = _stub_registry(monkeypatch)
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
    assert registered == [("unknown-job", "workspace")]
    assert forgotten == [("unknown-job", "workspace")]


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


@pytest.fixture
def block_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Replace the Prefect block seams with a dict-based fake store."""
    store: dict[str, list[str]] = {}

    monkeypatch.setattr(
        scitas_compute,
        "_read_registered_jobs",
        lambda workspace_name: list(store.get(workspace_name, [])),
    )

    def fake_write(workspace_name: str, job_names: list[str]) -> None:
        store[workspace_name] = list(job_names)

    monkeypatch.setattr(scitas_compute, "_write_registered_jobs", fake_write)
    return store


def test_registry_register_list_and_forget(block_store: dict[str, list[str]]) -> None:
    scitas_compute.register_job("job-1", "ws")
    scitas_compute.register_job("job-2", "ws")
    scitas_compute.register_job("job-1", "ws")

    assert scitas_compute.list_registered_jobs("ws") == ["job-1", "job-2"]
    assert scitas_compute.list_registered_jobs("missing") == []
    assert block_store["ws"] == ["job-1", "job-2"]

    scitas_compute.forget_job("job-1", "ws")
    scitas_compute.forget_job("unknown", "ws")
    assert scitas_compute.list_registered_jobs("ws") == ["job-2"]


def test_registry_rejects_unsafe_workspace_names() -> None:
    for ws in ("", ".", "..", "a/b"):
        with pytest.raises(ValueError):
            scitas_compute.register_job("job-1", ws)
        with pytest.raises(ValueError):
            scitas_compute.list_registered_jobs(ws)
        with pytest.raises(ValueError):
            scitas_compute.cancel_registered_jobs(ws)


def test_registry_cancels_only_active_jobs_and_forgets_them(
    block_store: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scitas_compute.register_job("running-1", "ws")
    scitas_compute.register_job("done-1", "ws")
    scitas_compute.register_job("unknown-1", "ws")
    statuses = {
        "running-1": "RUNNING",
        "done-1": "COMPLETED",
        "unknown-1": None,
    }
    cancelled: list[str] = []
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_job_status",
        lambda job_name: statuses[job_name],
    )
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "cancel_job",
        lambda job_name: cancelled.append(job_name),
    )

    cancelled_names = scitas_compute.cancel_registered_jobs("ws")

    assert cancelled_names == ["running-1"]
    assert cancelled == ["running-1"]
    assert scitas_compute.list_registered_jobs("ws") == []


@pytest.mark.parametrize("failure", ["status", "cancel"])
def test_registry_keeps_entries_and_continues_after_failure(
    block_store: dict[str, list[str]],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    scitas_compute.register_job("broken-1", "ws")
    scitas_compute.register_job("ok-1", "ws")
    cancelled: list[str] = []

    def fail_status(job_name: str) -> str:
        if job_name == "broken-1":
            raise RuntimeError("SSH down")
        return "RUNNING"

    def fail_cancel(job_name: str) -> None:
        if job_name == "broken-1":
            raise RuntimeError("scancel failed")
        cancelled.append(job_name)

    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_job_status",
        fail_status if failure == "status" else lambda job_name: "RUNNING",
    )
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "cancel_job",
        fail_cancel
        if failure == "cancel"
        else lambda job_name: cancelled.append(job_name),
    )

    cancelled_names = scitas_compute.cancel_registered_jobs("ws")

    assert cancelled_names == ["ok-1"]
    assert cancelled == ["ok-1"]
    # Keep the failed entry, so a later call can retry the cancellation.
    assert scitas_compute.list_registered_jobs("ws") == ["broken-1"]
