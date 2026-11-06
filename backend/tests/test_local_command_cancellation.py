import asyncio
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from textwrap import dedent

import anyio
import pytest

from api.lib.utils.commands import Command, CommandExecutionError
from api.lib.utils.commands.environments import local
from api.lib.workflows import splat_generation as workflow


def _command(tool: local.CommandTool = "ffmpeg", *, streaming: bool = False) -> Command:
    script = dedent(f"""
        import signal, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print('ready', flush=True)
        while True:
            if {streaming!r}:
                print('progress', flush=True)
            time.sleep(0.01)
    """)
    return Command(tool=tool, arguments=("-c", script), capture="combined")


@pytest.fixture
def environment(monkeypatch: pytest.MonkeyPatch):
    instance = local.LocalCommandExecutionEnvironment()
    monkeypatch.setattr(instance, "_resolve_tool", lambda tool: sys.executable)
    yield instance
    instance.cancel()


@pytest.fixture
def processes(monkeypatch: pytest.MonkeyPatch):
    started: list[subprocess.Popen] = []
    popen = subprocess.Popen

    def start(*args, **kwargs):
        process = popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(local.subprocess, "Popen", start)
    return started


def _assert_closed(process: subprocess.Popen) -> None:
    assert process.returncode is not None
    for pipe in (process.stdout, process.stderr):
        if pipe is not None:
            assert pipe.closed


@pytest.mark.parametrize("tool", ["ffmpeg", "brush"])
@pytest.mark.parametrize("streaming", [False, True])
def test_cancel_kills_and_reaps_command(
    environment,
    processes,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tool: local.CommandTool,
    streaming: bool,
) -> None:
    descriptors: list[int] = []
    openpty = local.pty.openpty

    def track_pty():
        pair = openpty()
        descriptors.extend(pair)
        return pair

    monkeypatch.setattr(local.pty, "openpty", track_pty)
    ready = threading.Event()
    records: list[str] = []

    def on_log(record: str) -> None:
        records.append(record)
        ready.set()

    with ThreadPoolExecutor() as pool:
        execution = pool.submit(
            environment.execute,
            _command(tool, streaming=streaming),
            workspace=tmp_path,
            on_log=on_log,
        )
        try:
            assert ready.wait(5)
        finally:
            environment.cancel()
        with pytest.raises(CommandExecutionError, match="cancelled"):
            execution.result(timeout=5)

    assert processes[0].returncode == -signal.SIGKILL
    _assert_closed(processes[0])
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert records[0] == "ready"
    environment.cancel()


def test_cancel_prevents_late_process_start(
    environment, processes, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    resolving = threading.Event()
    release = threading.Event()

    def resolve(tool: local.CommandTool) -> str:
        resolving.set()
        assert release.wait(5)
        return sys.executable

    monkeypatch.setattr(environment, "_resolve_tool", resolve)
    with ThreadPoolExecutor() as pool:
        execution = pool.submit(environment.execute, _command(), workspace=tmp_path)
        try:
            assert resolving.wait(5)
            environment.cancel()
        finally:
            release.set()
        with pytest.raises(CommandExecutionError, match="cancelled"):
            execution.result(timeout=5)

    assert processes == []


def test_cancel_during_process_creation(
    environment, processes, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    spawning = threading.Event()
    release = threading.Event()
    cancelling = threading.Event()
    popen = local.subprocess.Popen

    def delayed_start(*args, **kwargs):
        spawning.set()
        assert release.wait(5)
        return popen(*args, **kwargs)

    def cancel() -> None:
        cancelling.set()
        environment.cancel()

    monkeypatch.setattr(local.subprocess, "Popen", delayed_start)
    with ThreadPoolExecutor() as pool:
        execution = pool.submit(environment.execute, _command(), workspace=tmp_path)
        try:
            assert spawning.wait(5)
            cancellation = pool.submit(cancel)
            assert cancelling.wait(5)
            assert not cancellation.done()
        finally:
            release.set()
        cancellation.result(timeout=5)
        with pytest.raises(CommandExecutionError, match="cancelled"):
            execution.result(timeout=5)

    assert len(processes) == 1
    assert processes[0].returncode == -signal.SIGKILL
    _assert_closed(processes[0])


def test_cancel_waits_for_callback_and_discards_buffered_records(
    environment, processes, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    callback_started = threading.Event()
    release_callback = threading.Event()
    kill_requested = threading.Event()
    records: list[str] = []
    kill = local._kill_process_group

    def track_kill(process) -> None:
        kill(process)
        kill_requested.set()

    def on_log(record: str) -> None:
        records.append(record)
        callback_started.set()
        assert release_callback.wait(5)

    monkeypatch.setattr(local, "_kill_process_group", track_kill)
    command = Command(
        tool="ffmpeg",
        arguments=("-c", "print('ready'); print('buffered')"),
        capture="combined",
    )
    with ThreadPoolExecutor() as pool:
        execution = pool.submit(
            environment.execute, command, workspace=tmp_path, on_log=on_log
        )
        try:
            assert callback_started.wait(5)
            # Let the command finish before cancellation: its exit is a race too.
            processes[0].wait(timeout=5)
            cancellation = pool.submit(environment.cancel)
            assert kill_requested.wait(5)
            assert not cancellation.done()
        finally:
            release_callback.set()
        cancellation.result(timeout=5)
        with pytest.raises(CommandExecutionError, match="cancelled"):
            execution.result(timeout=5)

    assert records == ["ready"]
    _assert_closed(processes[0])


@pytest.mark.parametrize("leader_exits", [False, True])
def test_cancel_kills_descendants(
    environment, processes, tmp_path: Path, leader_exits: bool
) -> None:
    ready = threading.Event()
    records: list[str] = []
    child_script = "import time; print('child-ready', flush=True); time.sleep(60)"
    script = dedent(f"""
        import subprocess, sys, time
        child = subprocess.Popen([sys.executable, '-c', {child_script!r}])
        print(f'child={{child.pid}}', flush=True)
        if not {leader_exits!r}:
            time.sleep(60)
    """)

    def on_log(record: str) -> None:
        records.append(record)
        if len(records) == 2:
            ready.set()

    with ThreadPoolExecutor() as pool:
        execution = pool.submit(
            environment.execute,
            Command(tool="colmap", arguments=("-c", script), capture="combined"),
            workspace=tmp_path,
            on_log=on_log,
        )
        try:
            assert ready.wait(5)
            if leader_exits:
                assert processes[0].wait(timeout=5) == 0
        finally:
            environment.cancel()
        with pytest.raises(CommandExecutionError, match="cancelled"):
            execution.result(timeout=5)

    child_pid = int(
        next(record for record in records if record.startswith("child="))[6:]
    )
    # An orphan may briefly remain a zombie until the OS reaps it.
    status = subprocess.run(
        ["ps", "-p", str(child_pid), "-o", "stat="],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    assert not status or status.startswith("Z")
    _assert_closed(processes[0])


def test_cancel_isolates_environments(
    environment, processes, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    other = local.LocalCommandExecutionEnvironment()
    monkeypatch.setattr(other, "_resolve_tool", lambda tool: sys.executable)
    ready = [threading.Event(), threading.Event()]
    with ThreadPoolExecutor() as pool:
        executions = [
            pool.submit(
                instance.execute,
                _command(),
                workspace=tmp_path,
                on_log=lambda record, event=event: event.set(),
            )
            for instance, event in zip((environment, other), ready)
        ]
        try:
            assert all(event.wait(5) for event in ready)
            environment.cancel()
            assert not executions[1].done()
            assert sum(process.poll() is None for process in processes) == 1
        finally:
            other.cancel()
        for execution in executions:
            with pytest.raises(CommandExecutionError, match="cancelled"):
                execution.result(timeout=5)


@pytest.mark.parametrize("cancellation", ["asyncio", "anyio"])
@pytest.mark.parametrize("tool", ["ffmpeg", "brush"])
def test_async_cancellation_waits_for_output_cleanup(
    environment, processes, tmp_path: Path, cancellation: str, tool: local.CommandTool
) -> None:
    records: list[str] = []

    async def run() -> None:
        ready = anyio.Event()

        async def record_log(record: str) -> None:
            records.append(record)
            ready.set()

        operation = partial(
            environment.execute,
            _command(tool, streaming=True),
            workspace=tmp_path,
            on_log=lambda record: anyio.from_thread.run(record_log, record),
        )
        compute = partial(
            workflow._run_command_compute,
            operation,
            execution_environment=environment,
        )
        with anyio.fail_after(5):
            if cancellation == "asyncio":
                task = asyncio.create_task(compute())
                await ready.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                async with anyio.create_task_group() as tasks:
                    tasks.start_soon(compute)
                    await ready.wait()
                    tasks.cancel_scope.cancel()

        _assert_closed(processes[0])
        assert processes[0].returncode == -signal.SIGKILL
        snapshot = records.copy()
        await anyio.sleep(0.02)
        assert records == snapshot

    asyncio.run(run())


def test_prefect_sigterm_cleans_up_before_interpreter_shutdown(tmp_path: Path) -> None:
    ready_path = tmp_path / "command.pid"
    script = dedent(r"""
        import asyncio, os, signal, sys, threading
        from functools import partial
        from pathlib import Path
        from prefect._internal import control_listener
        from prefect.exceptions import TerminationSignal
        from prefect.utilities.engine import capture_sigterm
        from api.lib.utils.commands import Command, LocalCommandExecutionEnvironment
        from api.lib.workflows.splat_generation import _run_command_compute

        ready_path = Path(sys.argv[1])
        environment = LocalCommandExecutionEnvironment()
        environment._resolve_tool = lambda tool: sys.executable
        child_script = (
            'import os, pathlib, signal, sys, time; '
            'signal.signal(signal.SIGTERM, signal.SIG_IGN); '
            'pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); '
            '\nwhile True:\n'
            '    print("progress", flush=True)\n'
            '    time.sleep(0.01)\n'
        )

        def on_log(record):
            assert not threading._SHUTTING_DOWN, 'Log emitted during shutdown'

        async def main():
            await _run_command_compute(
                partial(
                    environment.execute,
                    Command('colmap', ('-c', child_script, str(ready_path)), 'combined'),
                    workspace=ready_path.parent,
                    on_log=on_log,
                ),
                execution_environment=environment,
            )

        try:
            with capture_sigterm():
                # Model the runner's acknowledged cancellation intent before SIGTERM.
                control_listener._set_intent('cancel')
                asyncio.run(main())
        except TerminationSignal:
            assert not environment._running
            print('cleaned', flush=True)
    """)
    flow = subprocess.Popen(
        [sys.executable, "-c", script, str(ready_path)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_path.exists() and flow.poll() is None:
            assert time.monotonic() < deadline, "Command did not start"
            time.sleep(0.01)
        assert ready_path.exists(), flow.communicate(timeout=5)
        command_pid = int(ready_path.read_text())
        flow.send_signal(signal.SIGTERM)
        stdout, stderr = flow.communicate(timeout=10)
        assert flow.returncode == 0, stderr
        assert stdout.strip() == "cleaned"
        assert "Logging error" not in stderr
        assert "Log emitted during shutdown" not in stderr
        with pytest.raises(ProcessLookupError):
            os.kill(command_pid, 0)
    finally:
        if flow.poll() is None:
            flow.kill()
        flow.communicate(timeout=5)
        if ready_path.exists():
            try:
                os.kill(int(ready_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
