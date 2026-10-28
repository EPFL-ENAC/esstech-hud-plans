import tomllib
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _load_toml(name: str) -> dict:
    with open(BACKEND_ROOT / name, "rb") as f:
        return tomllib.load(f)


def _dockerfile_text() -> str:
    return (BACKEND_ROOT / "Dockerfile").read_text()


def test_plyfile_is_a_main_dependency() -> None:
    pyproject = _load_toml("pyproject.toml")
    dependencies = [d.lower() for d in pyproject["project"]["dependencies"]]
    assert any(d.startswith("plyfile") for d in dependencies)


def test_retired_dependencies_are_not_declared() -> None:
    pyproject = _load_toml("pyproject.toml")
    dependencies = {d.split(">=")[0] for d in pyproject["project"]["dependencies"]}
    assert dependencies.isdisjoint(
        {"fastapi-cache2", "pandas", "openpyxl", "cachetools", "jinja2"}
    )
    assert "blueprint" not in pyproject["project"]["optional-dependencies"]


def test_uv_lock_tracks_plyfile_as_main_dependency() -> None:
    lock = _load_toml("uv.lock")
    assert lock["requires-python"] == "==3.12.*"
    root = next(p for p in lock["package"] if p["name"] == "backend")
    requires_dist = root["metadata"]["requires-dist"]
    plyfile = next(d for d in requires_dist if d["name"] == "plyfile")
    assert "extra" not in plyfile.get("marker", "")
    assert plyfile["specifier"] == ">=1.1.3"


def test_uv_lock_pins_pycolmap_3_13_0() -> None:
    lock = _load_toml("uv.lock")
    pycolmap = next(p for p in lock["package"] if p["name"] == "pycolmap")
    assert pycolmap["version"] == "3.13.0"


def test_dockerfile_uses_locked_sync_on_supported_python() -> None:
    dockerfile = _dockerfile_text()
    assert dockerfile.startswith("FROM python:3.12-bookworm")
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "uv pip install" not in dockerfile
    assert any(
        line.startswith("ENV PATH") and "/app/.venv/bin" in line
        for line in dockerfile.splitlines()
    )


def test_dockerfile_keeps_system_packages_and_ffmpeg_symlink() -> None:
    dockerfile = _dockerfile_text()
    for package in ("libglew-dev", "ffmpeg", "rsync"):
        assert package in dockerfile
    assert "rclone" not in dockerfile
    assert "ln -s $(which ffmpeg) /app/external/bin/ffmpeg" in dockerfile
