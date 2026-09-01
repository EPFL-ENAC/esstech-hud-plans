from pathlib import Path

import pytest
from api.lib.compute import colmap
from api.models.workflows import ColmapSettings


def _create_frame(frames_directory: Path) -> None:
    frames_directory.mkdir(parents=True)
    (frames_directory / "frame_00001.jpg").touch()


def _create_sparse_model(colmap_directory: Path) -> None:
    model_directory = colmap_directory / "sparse" / "0"
    model_directory.mkdir(parents=True, exist_ok=True)
    for filename in ("cameras.bin", "images.bin", "points3D.bin"):
        (model_directory / filename).touch()


def test_resolve_colmap_command_falls_back_to_system_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(colmap, "COLMAP_COMMAND", tmp_path / "missing-colmap")
    monkeypatch.setattr(colmap.shutil, "which", lambda command: "/usr/bin/colmap")

    assert colmap._resolve_colmap_command() == "/usr/bin/colmap"


def test_build_colmap_command_handles_paths_and_global_mapper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(colmap, "_resolve_colmap_command", lambda: "/colmap bin")
    frames_directory = tmp_path / "input frames"
    colmap_directory = tmp_path / "COLMAP workspace"

    command = colmap.build_colmap_command(
        frames_directory,
        colmap_directory,
        ColmapSettings(
            data_type="internet",
            quality="high",
            camera_model="RADIAL",
            single_camera=False,
            use_gpu=True,
            use_global_mapper=True,
        ),
    )

    assert command == [
        "/colmap bin",
        "automatic_reconstructor",
        "--image_path",
        str(frames_directory),
        "--workspace_path",
        str(colmap_directory),
        "--camera_model",
        "RADIAL",
        "--dense",
        "0",
        "--data_type",
        "internet",
        "--quality",
        "high",
        "--single_camera",
        "0",
        "--use_gpu",
        "1",
        "--mapper",
        "global",
    ]


def test_run_colmap_reconstruction_uses_combined_logs_and_returns_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frames_directory = tmp_path / "frames"
    colmap_directory = tmp_path / "colmap"
    _create_frame(frames_directory)
    captured: dict = {}

    def fake_run_logged_command(command, **kwargs) -> None:
        captured["command"] = command
        captured.update(kwargs)
        kwargs["on_log"]("feature extraction")
        kwargs["on_log"]("mapping")
        _create_sparse_model(colmap_directory)

    monkeypatch.setattr(colmap, "run_logged_command", fake_run_logged_command)
    monkeypatch.setattr(colmap, "_resolve_colmap_command", lambda: "colmap")
    records: list[str] = []
    on_log = records.append

    result = colmap.run_colmap_reconstruction(
        frames_directory,
        colmap_directory,
        ColmapSettings(),
        on_log=on_log,
    )

    assert result == colmap_directory.resolve()
    assert records == ["feature extraction", "mapping"]
    gpu_option_index = captured["command"].index("--use_gpu")
    assert captured["command"][gpu_option_index + 1] == "0"
    assert captured["capture"] == "combined"
    assert captured["log_prefix"] == "colmap"
    assert captured["fallback_logger"] is colmap.logger
    assert captured["on_log"] is on_log


def test_run_colmap_reconstruction_requires_frames(tmp_path: Path) -> None:
    frames_directory = tmp_path / "frames"
    frames_directory.mkdir()

    with pytest.raises(RuntimeError, match="contains no JPEG frames"):
        colmap.run_colmap_reconstruction(
            frames_directory,
            tmp_path / "colmap",
            ColmapSettings(),
        )


def test_run_colmap_reconstruction_requires_valid_sparse_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    frames_directory = tmp_path / "frames"
    _create_frame(frames_directory)
    monkeypatch.setattr(colmap, "run_logged_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(colmap, "_resolve_colmap_command", lambda: "colmap")

    with pytest.raises(RuntimeError, match="valid sparse/0 reconstruction"):
        colmap.run_colmap_reconstruction(
            frames_directory,
            tmp_path / "colmap",
            ColmapSettings(),
        )
