import os
import subprocess
from pathlib import Path

import pytest

BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


def test_entrypoint_replaces_itself_with_the_requested_command() -> None:
    environment = os.environ.copy()
    environment.pop("SSH_PRIVATE_KEY", None)

    with subprocess.Popen(
        [
            "sh",
            str(BACKEND_DIRECTORY / "start.sh"),
            "sh",
            "-c",
            'printf "%s\\n%s\\n" "$$" "$1"; exit 17',
            "startup-test",
            "argument with spaces",
        ],
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        stdout, stderr = process.communicate(timeout=10)

    assert process.returncode == 17, stderr
    assert stdout.splitlines() == [str(process.pid), "argument with spaces"]


@pytest.mark.parametrize("migration_exit_code", [0, 1])
def test_api_starts_only_after_successful_migrations(
    tmp_path: Path,
    migration_exit_code: int,
) -> None:
    startup_log = tmp_path / "startup.log"
    commands = {
        "alembic": (
            '#!/bin/sh\nprintf "alembic:%s\\n" "$*" >> "$STARTUP_LOG"\n'
            'exit "$MIGRATION_EXIT_CODE"\n'
        ),
        "uvicorn": ('#!/bin/sh\nprintf "uvicorn:%s\\n" "$*" >> "$STARTUP_LOG"\n'),
    }
    for name, content in commands.items():
        command = tmp_path / name
        command.write_text(content)
        command.chmod(0o755)

    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.defpath}",
        "STARTUP_LOG": str(startup_log),
        "MIGRATION_EXIT_CODE": str(migration_exit_code),
    }
    result = subprocess.run(
        ["sh", str(BACKEND_DIRECTORY / "start-api.sh")],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == migration_exit_code, result.stderr
    expected_log = ["alembic:upgrade head"]
    if migration_exit_code == 0:
        expected_log.append(
            "uvicorn:--host=0.0.0.0 --timeout-keep-alive=0 api.main:app"
        )
    assert startup_log.read_text().splitlines() == expected_log
