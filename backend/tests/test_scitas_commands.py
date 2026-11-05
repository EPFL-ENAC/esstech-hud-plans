import asyncio
import os
import shlex
import subprocess
import threading
from pathlib import Path, PurePosixPath

import pytest

from api.lib.compute import scitas as scitas_compute
from api.lib.compute.progress import SpirulaTrainProgressEstimator
from api.lib.utils import commands
from api.lib.utils.commands.environments import scitas as scitas_commands


@pytest.mark.parametrize("fails", [False, True])
def test_scitas_run_offloads_operation_and_preserves_outcome(fails: bool) -> None:
    environment = scitas_commands.ScitasCommandExecutionEnvironment()
    event_loop_thread = threading.get_ident()
    result = object()
    failure = RuntimeError("Operation failed")

    def operation() -> object:
        assert threading.get_ident() != event_loop_thread
        if fails:
            raise failure
        return result

    if fails:
        with pytest.raises(RuntimeError) as error:
            asyncio.run(environment.run(operation))
        assert error.value is failure
    else:
        assert asyncio.run(environment.run(operation)) is result


def test_scitas_log_tail_feeds_incremental_progress_across_polls(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "spirula.log"
    tail = scitas_commands._IncrementalLogTail()
    estimator = SpirulaTrainProgressEstimator()
    updates: list[float] = []

    def report(record: str) -> None:
        if (progress := estimator.feed(record)) is not None:
            updates.append(progress)

    log_path.write_bytes(
        b"Loading config\n\x1b[2Kstep   100/1000  ( 10%)\rstep   200/10"
    )
    tail.read(log_path, report)
    assert updates == [0.1]
    tail.read(log_path, report)
    assert updates == [0.1]  # Re-reading must not replay old records.

    with log_path.open("ab") as stream:
        stream.write(b"00  ( 20%)\rstep   300/1000  ( 30%)")
    tail.read(log_path, report)
    assert updates == [0.1, 0.2]
    tail.finish(report)
    assert updates == [0.1, 0.2, 0.3]


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


def test_scitas_environment_submits_and_streams_workspace_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    log_path = tmp_path / "job.log"
    calls: list[tuple] = []
    status_checks = 0
    registered, forgotten = _stub_registry(monkeypatch)

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

    monkeypatch.setattr(scitas_compute.Scitas, "submit_job", submit_job)
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_log_file_path",
        lambda job_name: str(log_path),
    )
    monkeypatch.setattr(scitas_compute.Scitas, "get_job_status", get_status)
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_job_result",
        lambda job_name: scitas_compute.ScitasJobResult("COMPLETED", 0),
    )
    sleeps: list[float] = []
    monkeypatch.setattr(scitas_commands.time, "sleep", sleeps.append)

    environment = commands.ScitasCommandExecutionEnvironment(
        poll_interval_seconds=0.25,
        remote_workspace_prefix=PurePosixPath("remote jobs"),
    )
    command = commands.Command(
        tool="spirula",
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
    assert calls == [
        (
            "submit",
            {
                "tool": "spirula",
                "command": [
                    "spirula",
                    "--image_path",
                    "frames directory",
                ],
                "workspace_rel_path": remote_workspace,
                "capture": "combined",
            },
        ),
    ]


def test_scitas_environment_reports_failure_and_forgets_finished_job(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    cancelled: list[str] = []

    monkeypatch.setattr(
        scitas_compute.Scitas, "submit_job", lambda **kwargs: "failed-job"
    )
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_log_file_path",
        lambda job_name: str(tmp_path / "missing.log"),
    )
    monkeypatch.setattr(
        scitas_compute.Scitas, "get_job_status", lambda job_name: "FAILED"
    )
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_job_result",
        lambda job_name: scitas_compute.ScitasJobResult("FAILED", 42),
    )
    monkeypatch.setattr(scitas_compute.Scitas, "cancel_job", cancelled.append)
    registered, forgotten = _stub_registry(monkeypatch)

    command = commands.Command(tool="spirula", arguments=(), capture="combined")
    environment = commands.ScitasCommandExecutionEnvironment(poll_interval_seconds=0)

    with pytest.raises(commands.CommandExecutionError) as error:
        environment.execute(command, workspace=workspace)

    assert error.value.command == command
    assert error.value.return_code == 42
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
        scitas_compute.Scitas, "submit_job", lambda **kwargs: "running-job"
    )
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_log_file_path",
        lambda job_name: str(log_path),
    )
    monkeypatch.setattr(scitas_compute.Scitas, "cancel_job", cancelled.append)
    registered, forgotten = _stub_registry(monkeypatch)

    def fail_to_log(record: str) -> None:
        raise RuntimeError(f"Could not log: {record}")

    environment = commands.ScitasCommandExecutionEnvironment(poll_interval_seconds=0)

    with pytest.raises(RuntimeError, match="Could not log: record"):
        environment.execute(
            commands.Command(tool="spirula", arguments=(), capture="combined"),
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
        scitas_compute.Scitas, "submit_job", lambda **kwargs: "unknown-job"
    )
    monkeypatch.setattr(
        scitas_compute.Scitas,
        "get_log_file_path",
        lambda job_name: str(tmp_path / "missing.log"),
    )
    monkeypatch.setattr(scitas_compute.Scitas, "get_job_status", lambda job_name: None)
    monkeypatch.setattr(scitas_compute.Scitas, "cancel_job", cancelled.append)
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
            commands.Command(tool="spirula", arguments=(), capture="combined"),
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


@pytest.mark.parametrize("capture", ["stdout", "stderr", "combined"])
@pytest.mark.parametrize(
    ("command_status", "stage_out_status", "expected_status"),
    [(0, 0, 0), (42, 0, 42), (0, 23, 23), (42, 23, 42)],
)
def test_scitas_submit_job_uses_workspace_cwd_capture_and_failure_safe_stage_out(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capture: commands.CommandLogCapture,
    command_status: int,
    stage_out_status: int,
    expected_status: int,
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

    export_root = tmp_path / "export's directory"
    scratch_root = tmp_path / "scratch's directory"
    images_root = tmp_path / "image's directory"
    workspace = "workflows/job's directory"
    export_workspace = export_root / workspace
    export_workspace.mkdir(parents=True)
    (export_workspace / "input.txt").write_text("input")
    monkeypatch.setattr(
        scitas_compute.config, "SCITAS_REMOTE_EXPORT_PATH", str(export_root)
    )
    monkeypatch.setattr(
        scitas_compute.config, "SCITAS_REMOTE_SCRATCH_PATH", str(scratch_root)
    )
    monkeypatch.setattr(
        scitas_compute.config, "SCITAS_REMOTE_IMAGES_PATH", str(images_root)
    )
    job_name = scitas_compute.Scitas.submit_job(
        tool="spirula",
        command=["spirula", "--image_path", "frames directory"],
        workspace_rel_path=workspace,
        capture=capture,
    )

    assert len(written_scripts) == 1
    script = written_scripts[0]
    expected_log = str(export_root / "log" / f"{job_name}.log")
    stdout_path = "/dev/null" if capture == "stderr" else expected_log
    stderr_path = "/dev/null" if capture == "stdout" else expected_log
    for stream, path in (("output", stdout_path), ("error", stderr_path)):
        directive = next(
            line.removeprefix("#SBATCH ")
            for line in script.splitlines()
            if line.startswith(f"#SBATCH --{stream}=")
        )
        assert shlex.split(directive) == [f"--{stream}={path}"]

    # Execute the generated script against local tools to verify staging order,
    # argument quoting, the working directory, and both failure exit codes.
    tools_directory = tmp_path / "bin"
    tools_directory.mkdir()
    rsync = tools_directory / "rsync"
    rsync.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        'if [[ "$3" == "$HUD_TEST_SCRATCH/"* ]]; then\n'
        '    echo stage-out >> "$HUD_TEST_EVENTS"\n'
        '    if [ "$HUD_TEST_STAGE_OUT_STATUS" -ne 0 ]; then\n'
        '        exit "$HUD_TEST_STAGE_OUT_STATUS"\n'
        "    fi\n"
        "else\n"
        '    echo stage-in >> "$HUD_TEST_EVENTS"\n'
        "fi\n"
        'cp -R "$3." "$4"\n'
    )
    apptainer = tools_directory / "apptainer"
    apptainer.write_text(
        "#!/bin/bash\n"
        "set -eu\n"
        'echo run >> "$HUD_TEST_EVENTS"\n'
        'pwd > "$HUD_TEST_CWD"\n'
        'printf "%s\\0" "$@" > "$HUD_TEST_ARGUMENTS"\n'
        'test "$(cat input.txt)" = input\n'
        "echo output > result.txt\n"
        'exit "$HUD_TEST_COMMAND_STATUS"\n'
    )
    rsync.chmod(0o755)
    apptainer.chmod(0o755)
    events_path = tmp_path / "events"
    cwd_path = tmp_path / "cwd"
    arguments_path = tmp_path / "arguments"
    result = subprocess.run(
        ["bash"],
        input=script,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PATH": f"{tools_directory}{os.pathsep}{os.environ['PATH']}",
            "HUD_TEST_SCRATCH": str(scratch_root),
            "HUD_TEST_EVENTS": str(events_path),
            "HUD_TEST_CWD": str(cwd_path),
            "HUD_TEST_ARGUMENTS": str(arguments_path),
            "HUD_TEST_COMMAND_STATUS": str(command_status),
            "HUD_TEST_STAGE_OUT_STATUS": str(stage_out_status),
        },
    )

    assert result.returncode == expected_status, result.stderr
    assert events_path.read_text().splitlines() == ["stage-in", "run", "stage-out"]
    assert (
        Path(cwd_path.read_text().strip()).resolve()
        == (scratch_root / workspace).resolve()
    )
    assert arguments_path.read_bytes().split(b"\0")[:-1] == [
        argument.encode()
        for argument in (
            "exec",
            "--nv",
            str(images_root / "hud-spirula_latest.sif"),
            "spirula",
            "--image_path",
            "frames directory",
        )
    ]
    if stage_out_status == 0:
        assert (export_workspace / "result.txt").read_text().strip() == "output"


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
