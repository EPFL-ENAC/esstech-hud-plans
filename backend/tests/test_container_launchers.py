import os
import subprocess
import sys
from pathlib import Path

import pytest

DOCKER_DIRECTORY = Path(__file__).resolve().parents[2] / "docker"
VOCABULARY_NAME = (
    "96ca8ec8ea60b1f73465aaf2c401fd3b3ca75cdba2d3c50d6a2f6f760f275ddc-"
    "vocab_tree_faiss_flickr100K_words256K.bin"
)


def _write_executable(path: Path, source: str) -> None:
    path.write_text(source)
    path.chmod(0o755)


@pytest.mark.parametrize("exit_status", [0, 42])
@pytest.mark.parametrize("existing_cache", [False, True])
def test_colmap_launcher_seeds_cache_and_forwards_arguments_and_exit_status(
    tmp_path: Path,
    exit_status: int,
    existing_cache: bool,
) -> None:
    home = tmp_path / "user's home"
    home.mkdir()
    packaged_cache = tmp_path / "packaged cache"
    packaged_cache.mkdir()
    packaged_vocabulary = packaged_cache / VOCABULARY_NAME
    cached_vocabulary = home / ".cache" / "colmap" / VOCABULARY_NAME
    if existing_cache:
        cached_vocabulary.parent.mkdir(parents=True)
        cached_vocabulary.write_text("existing vocabulary")
        # An existing cache must work without accessing the packaged copy.
    else:
        packaged_vocabulary.write_text("packaged vocabulary")

    executable = tmp_path / "colmap binary"
    _write_executable(
        executable,
        f'#!/bin/bash\nprintf "%s\\0" "$@"\nexit {exit_status}\n',
    )
    # Substitute container paths in a temporary copy, leaving the production
    # launcher and its fixed installation paths unchanged.
    launcher = tmp_path / "colmap launcher"
    source = (DOCKER_DIRECTORY / "colmap.sh").read_text()
    source = source.replace("/opt/hud/colmap-cache", str(packaged_cache))
    source = source.replace(
        'exec /usr/local/libexec/colmap "$@"', f'exec "{executable}" "$@"'
    )
    _write_executable(launcher, source)
    arguments = ["--image_path", "frames with spaces", "it's quoted", "", "a\nb"]

    result = subprocess.run(
        ["bash", str(launcher), *arguments],
        env={**os.environ, "HOME": str(home)},
        capture_output=True,
    )

    assert result.returncode == exit_status, result.stderr
    assert result.stdout.split(b"\0")[:-1] == [arg.encode() for arg in arguments]
    expected_vocabulary = (
        "existing vocabulary" if existing_cache else "packaged vocabulary"
    )
    assert cached_vocabulary.read_text() == expected_vocabulary
    assert list(cached_vocabulary.parent.iterdir()) == [cached_vocabulary]


def test_colmap_launcher_discards_incomplete_cache_when_copy_fails(
    tmp_path: Path,
) -> None:
    tools_directory = tmp_path / "bin"
    tools_directory.mkdir()
    _write_executable(
        tools_directory / "cp",
        '#!/bin/bash\nprintf partial > "$2"\nexit 37\n',
    )
    home = tmp_path / "home"

    result = subprocess.run(
        ["bash", str(DOCKER_DIRECTORY / "colmap.sh")],
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{tools_directory}{os.pathsep}{os.environ['PATH']}",
        },
        capture_output=True,
    )

    assert result.returncode == 37, result.stderr
    assert list((home / ".cache" / "colmap").iterdir()) == []


@pytest.mark.skipif(sys.platform != "linux", reason="Requires util-linux script")
@pytest.mark.parametrize("exit_status", [0, 42])
def test_brush_launcher_preserves_arguments_progress_and_exit_status(
    tmp_path: Path,
    exit_status: int,
) -> None:
    arguments_path = tmp_path / "arguments"
    executable = tmp_path / "brush binary"
    _write_executable(
        executable,
        "#!/bin/bash\n"
        "test -t 1 || exit 99\n"
        'printf "%s\\0" "$@" > "$HUD_TEST_ARGUMENTS"\n'
        'printf "first\\rsecond\\n"\n'
        f"exit {exit_status}\n",
    )
    launcher = tmp_path / "brush launcher"
    source = (DOCKER_DIRECTORY / "brush_unbuffered.sh").read_text()
    source = source.replace("/external/bin/brush", f'"{executable}"')
    _write_executable(launcher, source)
    arguments = ["frames with spaces", "it's quoted", "$(exit 99)", "", "a\nb"]

    result = subprocess.run(
        ["bash", str(launcher), *arguments],
        env={**os.environ, "HUD_TEST_ARGUMENTS": str(arguments_path)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )

    assert result.returncode == exit_status, result.stderr
    assert arguments_path.read_bytes().split(b"\0")[:-1] == [
        arg.encode() for arg in arguments
    ]
    assert b"first\nsecond" in result.stdout
    assert b"\r" not in result.stdout
