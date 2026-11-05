from pathlib import Path

import pytest

from api.lib.compute import spirula
from api.lib.utils.commands import (
    Command,
    CommandExecutionEnvironment,
    CommandResult,
    LogCallback,
)
from api.models.workflows import (
    SpirulaGeometrySettings,
    SpirulaSfmSettings,
    SpirulaTrainSettings,
)


class _NoOpEnvironment(CommandExecutionEnvironment):
    def execute(
        self,
        command: Command,
        *,
        workspace: Path,
        on_log: LogCallback | None = None,
    ) -> CommandResult:
        return CommandResult(return_code=0)


def _create_frames(frames_directory: Path) -> None:
    frames_directory.mkdir(parents=True)
    (frames_directory / "frame_00001.jpg").touch()


def _create_sparse_model(colmap_directory: Path) -> None:
    model_directory = colmap_directory / "sparse" / "0"
    model_directory.mkdir(parents=True, exist_ok=True)
    for filename in ("cameras.bin", "images.bin", "points3D.bin"):
        (model_directory / filename).touch()


def _create_train_dataset(dataset_directory: Path) -> None:
    _create_frames(dataset_directory / "frames")
    _create_sparse_model(dataset_directory / "colmap")


def test_build_sfm_command_uses_workspace_relative_paths_and_settings(
    tmp_path: Path,
) -> None:
    frames_directory = tmp_path / "input frames"
    colmap_directory = tmp_path / "COLMAP workspace"

    command = spirula.build_spirula_sfm_command(
        frames_directory,
        colmap_directory,
        SpirulaSfmSettings(
            data_type="internet",
            pairs="prefilter",
            quality="high",
            camera_model="radial",
            single_camera=False,
        ),
        workspace_directory=tmp_path,
    )

    assert command == Command(
        tool="spirula",
        arguments=(
            "sfm",
            "auto",
            "input frames",
            "--output",
            "COLMAP workspace",
            "--data-type",
            "internet",
            "--pairs",
            "prefilter",
            "--quality",
            "high",
            "--camera-model",
            "radial",
            "--camera-mode",
            "folder",
        ),
        capture="combined",
        acceptable_return_codes=(3,),
    )


@pytest.mark.parametrize(
    ("compute_depth", "compute_normals", "flag_arguments"),
    [
        (False, False, ("--no-normal",)),
        (True, True, ("--depth",)),
        (True, False, ("--depth", "--no-normal")),
        (False, True, ()),
    ],
)
def test_build_geometry_command_uses_workspace_relative_paths_and_flags(
    tmp_path: Path,
    compute_depth: bool,
    compute_normals: bool,
    flag_arguments: tuple[str, ...],
) -> None:
    dataset_directory = tmp_path / "dataset"

    command = spirula.build_spirula_geometry_command(
        dataset_directory,
        SpirulaGeometrySettings(
            compute_depth=compute_depth,
            compute_normals=compute_normals,
        ),
        workspace_directory=tmp_path,
    )

    assert command == Command(
        tool="spirula",
        arguments=(
            "geometry",
            "dataset",
            "--image-dir",
            "frames",
            *flag_arguments,
        ),
        capture="combined",
    )


@pytest.mark.parametrize(
    ("meshing_preset", "floater_suppression", "head_arguments", "tail_arguments"),
    [
        (True, True, ("meshing",), ("--floater-suppression", "mild")),
        (True, False, ("meshing",), ()),
        (
            False,
            True,
            (),
            ("--primitive", "mip", "--sh-degree", "2", "--floater-suppression", "mild"),
        ),
        (False, False, (), ("--primitive", "mip", "--sh-degree", "2")),
    ],
)
def test_build_train_command_uses_workspace_relative_paths_and_settings(
    tmp_path: Path,
    meshing_preset: bool,
    floater_suppression: bool,
    head_arguments: tuple[str, ...],
    tail_arguments: tuple[str, ...],
) -> None:
    splat_path = tmp_path / "outputs" / "scene.ply"

    command = spirula.build_spirula_train_command(
        tmp_path,
        splat_path,
        SpirulaTrainSettings(
            num_iterations=45_000,
            quality="high",
            primitive="mip",
            sh_degree=2,
            cap_max=500_000,
            floater_suppression=floater_suppression,
            meshing_preset=meshing_preset,
        ),
        workspace_directory=tmp_path,
    )

    assert command == Command(
        tool="spirula",
        arguments=(
            "train",
            *head_arguments,
            "--data",
            ".",
            "--image-dir",
            "frames",
            "--colmap-recon-dir",
            "colmap/sparse/0",
            "--output-dir-prefix",
            "outputs",
            "--output-dir-name",
            "train",
            "--disable-viewer",
            "1",
            "--num-iterations",
            "45000",
            "--quality",
            "high",
            *tail_arguments,
            "--cap-max",
            "500000",
        ),
        capture="combined",
    )


@pytest.mark.parametrize(
    "build",
    [
        lambda tmp_path: spirula.build_spirula_sfm_command(
            tmp_path.parent / "frames",
            tmp_path / "colmap",
            SpirulaSfmSettings(),
            workspace_directory=tmp_path,
        ),
        lambda tmp_path: spirula.build_spirula_geometry_command(
            tmp_path.parent / "dataset",
            SpirulaGeometrySettings(),
            workspace_directory=tmp_path,
        ),
        lambda tmp_path: spirula.build_spirula_train_command(
            tmp_path,
            tmp_path.parent / "splat.ply",
            SpirulaTrainSettings(),
            workspace_directory=tmp_path,
        ),
    ],
)
def test_build_commands_reject_paths_outside_workspace(tmp_path: Path, build) -> None:
    with pytest.raises(ValueError, match="must be inside workspace"):
        build(tmp_path)


def test_looks_like_colmap_model_accepts_binary_and_text_models(
    tmp_path: Path,
) -> None:
    assert not spirula.looks_like_colmap_model(tmp_path)

    model_directory = tmp_path / "0"
    model_directory.mkdir()
    assert not spirula.looks_like_colmap_model(model_directory)

    for filename in ("cameras.bin", "images.bin", "points3D.bin"):
        (model_directory / filename).touch()
    assert spirula.looks_like_colmap_model(model_directory)

    text_directory = tmp_path / "1"
    text_directory.mkdir()
    for filename in ("cameras.txt", "images.txt", "points3D.txt"):
        (text_directory / filename).touch()
    assert spirula.looks_like_colmap_model(text_directory)


def test_run_sfm_forwards_logs_and_returns_workspace(tmp_path: Path) -> None:
    frames_directory = tmp_path / "frames"
    colmap_directory = tmp_path / "colmap"
    _create_frames(frames_directory)
    captured: dict = {}

    class FakeEnvironment(CommandExecutionEnvironment):
        def execute(
            self,
            command: Command,
            *,
            workspace: Path,
            on_log: LogCallback | None = None,
        ) -> CommandResult:
            captured["command"] = command
            captured["workspace"] = workspace
            captured["on_log"] = on_log
            assert on_log is not None
            on_log("1/42   frame_00001.jpg   Features: 823")
            on_log("RESULT: OK")
            _create_sparse_model(colmap_directory)
            return CommandResult(return_code=0)

    records: list[str] = []
    on_log = records.append

    result = spirula.run_spirula_sfm(
        frames_directory,
        colmap_directory,
        SpirulaSfmSettings(),
        workspace_directory=tmp_path,
        execution_environment=FakeEnvironment(),
        on_log=on_log,
    )

    assert result == colmap_directory.resolve()
    assert records == ["1/42   frame_00001.jpg   Features: 823", "RESULT: OK"]
    assert captured["command"].capture == "combined"
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["on_log"] is on_log


def test_run_sfm_accepts_partial_reconstruction_return_code(tmp_path: Path) -> None:
    frames_directory = tmp_path / "frames"
    colmap_directory = tmp_path / "colmap"
    _create_frames(frames_directory)

    class PartialEnvironment(CommandExecutionEnvironment):
        def execute(
            self,
            command: Command,
            *,
            workspace: Path,
            on_log: LogCallback | None = None,
        ) -> CommandResult:
            _create_sparse_model(colmap_directory)
            return CommandResult(return_code=spirula.SFM_PARTIAL_RETURN_CODE)

    result = spirula.run_spirula_sfm(
        frames_directory,
        colmap_directory,
        SpirulaSfmSettings(),
        workspace_directory=tmp_path,
        execution_environment=PartialEnvironment(),
    )

    assert result == colmap_directory.resolve()


def test_run_sfm_requires_frames(tmp_path: Path) -> None:
    frames_directory = tmp_path / "frames"
    frames_directory.mkdir()

    with pytest.raises(RuntimeError, match="contains no JPEG frames"):
        spirula.run_spirula_sfm(
            frames_directory,
            tmp_path / "colmap",
            SpirulaSfmSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )


def test_run_sfm_requires_valid_sparse_model(tmp_path: Path) -> None:
    frames_directory = tmp_path / "frames"
    _create_frames(frames_directory)

    with pytest.raises(RuntimeError, match="valid sparse/0 reconstruction"):
        spirula.run_spirula_sfm(
            frames_directory,
            tmp_path / "colmap",
            SpirulaSfmSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )


def test_run_geometry_forwards_logs_and_returns_dataset(tmp_path: Path) -> None:
    _create_frames(tmp_path / "frames")
    captured: dict = {}

    class FakeEnvironment(CommandExecutionEnvironment):
        def execute(
            self,
            command: Command,
            *,
            workspace: Path,
            on_log: LogCallback | None = None,
        ) -> CommandResult:
            captured["command"] = command
            captured["workspace"] = workspace
            captured["on_log"] = on_log
            assert on_log is not None
            on_log("depth: frame_00001.jpg")
            on_log("normals: frame_00001.jpg")
            return CommandResult(return_code=0)

    records: list[str] = []
    on_log = records.append

    result = spirula.run_spirula_geometry(
        tmp_path,
        SpirulaGeometrySettings(compute_depth=True),
        workspace_directory=tmp_path,
        execution_environment=FakeEnvironment(),
        on_log=on_log,
    )

    assert result == tmp_path.resolve()
    assert records == ["depth: frame_00001.jpg", "normals: frame_00001.jpg"]
    assert captured["command"].arguments[:2] == ("geometry", ".")
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["on_log"] is on_log


def test_run_geometry_requires_frames(tmp_path: Path) -> None:
    (tmp_path / "frames").mkdir()

    with pytest.raises(RuntimeError, match="contains no JPEG frames"):
        spirula.run_spirula_geometry(
            tmp_path,
            SpirulaGeometrySettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )


def test_run_train_forwards_logs_and_moves_splat(tmp_path: Path) -> None:
    _create_train_dataset(tmp_path)
    splat_path = tmp_path / "outputs" / "scene.ply"
    run_splat_path = (
        tmp_path / "outputs" / "train" / "step-000030000.ckpt" / "splat.ply"
    )
    captured: dict = {}

    class FakeEnvironment(CommandExecutionEnvironment):
        def execute(
            self,
            command: Command,
            *,
            workspace: Path,
            on_log: LogCallback | None = None,
        ) -> CommandResult:
            captured["command"] = command
            captured["workspace"] = workspace
            captured["on_log"] = on_log
            assert on_log is not None
            on_log("step  15000/30000  ( 50%)  splats 900000")
            run_splat_path.parent.mkdir(parents=True)
            run_splat_path.touch()
            return CommandResult(return_code=0)

    records: list[str] = []
    on_log = records.append
    result = spirula.run_spirula_train(
        tmp_path,
        splat_path,
        SpirulaTrainSettings(),
        workspace_directory=tmp_path,
        execution_environment=FakeEnvironment(),
        on_log=on_log,
    )

    assert result == splat_path.resolve()
    assert splat_path.is_file()
    assert not run_splat_path.exists()
    assert records == ["step  15000/30000  ( 50%)  splats 900000"]
    assert captured["command"].arguments[:5] == (
        "train",
        "meshing",
        "--data",
        ".",
        "--image-dir",
    )
    assert captured["workspace"] == tmp_path.resolve()
    assert captured["on_log"] is on_log


@pytest.mark.parametrize(
    ("missing_path", "message"),
    [
        ("frames", "no extracted JPEG frames"),
        ("colmap", "no valid COLMAP sparse/0 reconstruction"),
    ],
)
def test_run_train_requires_complete_dataset(
    tmp_path: Path, missing_path: str, message: str
) -> None:
    _create_train_dataset(tmp_path)
    if missing_path == "frames":
        (tmp_path / "frames" / "frame_00001.jpg").unlink()
    else:
        for path in (tmp_path / "colmap" / "sparse" / "0").iterdir():
            path.unlink()
        (tmp_path / "colmap" / "sparse" / "0").rmdir()

    with pytest.raises(RuntimeError, match=message):
        spirula.run_spirula_train(
            tmp_path,
            tmp_path / "splat.ply",
            SpirulaTrainSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )


def test_run_train_requires_generated_splat(tmp_path: Path) -> None:
    _create_train_dataset(tmp_path)

    with pytest.raises(RuntimeError, match="without producing a splat PLY"):
        spirula.run_spirula_train(
            tmp_path,
            tmp_path / "splat.ply",
            SpirulaTrainSettings(),
            workspace_directory=tmp_path,
            execution_environment=_NoOpEnvironment(),
        )
