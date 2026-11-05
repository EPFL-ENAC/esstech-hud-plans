import shutil
from pathlib import Path

from api.lib.utils.commands import (
    Command,
    CommandExecutionEnvironment,
    LogCallback,
    workspace_relative_path,
)
from api.models.workflows import (
    SpirulaGeometrySettings,
    SpirulaSfmSettings,
    SpirulaTrainSettings,
)

# spirula train writes <output-dir-prefix>/<output-dir-name>/ containing the
# config and step-*.ckpt checkpoint directories; the trained PLY lives inside
# the final checkpoint as splat.ply. The run directory name is fixed so the
# runner can move the splat up to the artifact path the workflow expects.
TRAIN_RUN_DIRECTORY_NAME = "train"

# spirula sfm auto exits 3 for a partial reconstruction (<50% images
# registered). COLMAP tolerated partial models, so the model check below
# decides, not the exit code.
SFM_PARTIAL_RETURN_CODE = 3


def build_spirula_sfm_command(
    frames_directory: Path,
    colmap_directory: Path,
    settings: SpirulaSfmSettings,
    *,
    workspace_directory: Path,
) -> Command:
    relative_frames_directory = workspace_relative_path(
        frames_directory, workspace_directory
    )
    relative_colmap_directory = workspace_relative_path(
        colmap_directory, workspace_directory
    )
    return Command(
        tool="spirula",
        arguments=(
            "sfm",
            "auto",
            relative_frames_directory.as_posix(),
            "--output",
            relative_colmap_directory.as_posix(),
            "--data-type",
            settings.data_type,
            "--pairs",
            settings.pairs,
            "--quality",
            settings.quality,
            "--camera-model",
            settings.camera_model,
            "--camera-mode",
            "single" if settings.single_camera else "folder",
        ),
        capture="combined",
        acceptable_return_codes=(SFM_PARTIAL_RETURN_CODE,),
    )


def build_spirula_geometry_command(
    dataset_directory: Path,
    settings: SpirulaGeometrySettings,
    *,
    workspace_directory: Path,
) -> Command:
    relative_dataset_directory = workspace_relative_path(
        dataset_directory, workspace_directory
    )
    arguments = [
        "geometry",
        relative_dataset_directory.as_posix(),
        "--image-dir",
        "frames",
    ]
    if settings.compute_depth:
        arguments.append("--depth")
    if not settings.compute_normals:
        arguments.append("--no-normal")
    return Command(tool="spirula", arguments=tuple(arguments), capture="combined")


def build_spirula_train_command(
    dataset_directory: Path,
    splat_path: Path,
    settings: SpirulaTrainSettings,
    *,
    workspace_directory: Path,
) -> Command:
    relative_dataset_directory = workspace_relative_path(
        dataset_directory, workspace_directory
    )
    relative_splat_path = workspace_relative_path(splat_path, workspace_directory)
    export_directory = relative_splat_path.parent

    arguments = ["train"]
    if settings.meshing_preset:
        # The preset owns --primitive (Mip-Splats) and --sh-degree (0).
        arguments.append("meshing")
    arguments.extend(
        [
            "--data",
            relative_dataset_directory.as_posix(),
            "--image-dir",
            "frames",
            "--colmap-recon-dir",
            "colmap/sparse/0",
            "--output-dir-prefix",
            export_directory.as_posix(),
            "--output-dir-name",
            TRAIN_RUN_DIRECTORY_NAME,
            "--disable-viewer",
            "1",
            "--num-iterations",
            str(settings.num_iterations),
            "--quality",
            settings.quality,
        ]
    )
    if not settings.meshing_preset:
        arguments.extend(
            ["--primitive", settings.primitive, "--sh-degree", str(settings.sh_degree)]
        )
    if settings.floater_suppression:
        arguments.extend(["--floater-suppression", "mild"])
    arguments.extend(["--cap-max", str(settings.cap_max)])

    return Command(tool="spirula", arguments=tuple(arguments), capture="combined")


def looks_like_colmap_model(directory: Path) -> bool:
    if not directory.is_dir():
        return False

    filenames = {path.name for path in directory.iterdir() if path.is_file()}
    binary_model = {"cameras.bin", "images.bin", "points3D.bin"}
    text_model = {"cameras.txt", "images.txt", "points3D.txt"}
    return binary_model.issubset(filenames) or text_model.issubset(filenames)


def _validate_frames_directory(frames_directory: Path) -> None:
    if not frames_directory.is_dir():
        raise FileNotFoundError(f"Frames directory does not exist: {frames_directory}")
    if not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError(
            f"Frames directory contains no JPEG frames: {frames_directory}"
        )


def _validate_dataset_directory(dataset_directory: Path) -> None:
    frames_directory = dataset_directory / "frames"
    if not frames_directory.is_dir() or not any(frames_directory.glob("frame_*.jpg")):
        raise RuntimeError(
            f"Dataset contains no extracted JPEG frames: {frames_directory}"
        )

    sparse_directory = dataset_directory / "colmap" / "sparse" / "0"
    if not looks_like_colmap_model(sparse_directory):
        raise RuntimeError(
            f"Dataset contains no valid COLMAP sparse/0 reconstruction: {sparse_directory}"
        )


def run_spirula_sfm(
    frames_directory: Path,
    colmap_directory: Path,
    settings: SpirulaSfmSettings,
    *,
    workspace_directory: Path,
    execution_environment: CommandExecutionEnvironment,
    on_log: LogCallback | None = None,
) -> Path:
    """Run sparse reconstruction and return the COLMAP-format workspace."""

    workspace_directory = workspace_directory.resolve()
    frames_directory = frames_directory.resolve()
    colmap_directory = colmap_directory.resolve()

    command = build_spirula_sfm_command(
        frames_directory,
        colmap_directory,
        settings,
        workspace_directory=workspace_directory,
    )

    _validate_frames_directory(frames_directory)
    colmap_directory.mkdir(parents=True, exist_ok=True)
    execution_environment.execute(
        command,
        workspace=workspace_directory,
        on_log=on_log,
    )

    sparse_model_directory = colmap_directory / "sparse" / "0"
    if not looks_like_colmap_model(sparse_model_directory):
        raise RuntimeError(
            "spirula sfm completed without producing a valid sparse/0 reconstruction"
        )

    return colmap_directory


def run_spirula_geometry(
    dataset_directory: Path,
    settings: SpirulaGeometrySettings,
    *,
    workspace_directory: Path,
    execution_environment: CommandExecutionEnvironment,
    on_log: LogCallback | None = None,
) -> Path:
    """Predict depth/normal supervision maps beside the dataset."""

    workspace_directory = workspace_directory.resolve()
    dataset_directory = dataset_directory.resolve()

    command = build_spirula_geometry_command(
        dataset_directory,
        settings,
        workspace_directory=workspace_directory,
    )
    _validate_frames_directory(dataset_directory / "frames")
    execution_environment.execute(
        command,
        workspace=workspace_directory,
        on_log=on_log,
    )

    return dataset_directory


def run_spirula_train(
    dataset_directory: Path,
    splat_path: Path,
    settings: SpirulaTrainSettings,
    *,
    workspace_directory: Path,
    execution_environment: CommandExecutionEnvironment,
    on_log: LogCallback | None = None,
) -> Path:
    """Train a Gaussian splat and return the generated PLY path."""

    workspace_directory = workspace_directory.resolve()
    dataset_directory = dataset_directory.resolve()
    splat_path = splat_path.resolve()

    command = build_spirula_train_command(
        dataset_directory,
        splat_path,
        settings,
        workspace_directory=workspace_directory,
    )
    _validate_dataset_directory(dataset_directory)
    splat_path.parent.mkdir(parents=True, exist_ok=True)

    execution_environment.execute(
        command,
        workspace=workspace_directory,
        on_log=on_log,
    )

    run_splat_path = _find_trained_splat(splat_path.parent / TRAIN_RUN_DIRECTORY_NAME)
    if run_splat_path is None:
        raise RuntimeError("spirula train completed without producing a splat PLY")
    shutil.move(run_splat_path, splat_path)

    return splat_path


def _find_trained_splat(run_directory: Path) -> Path | None:
    """Locate the final checkpoint's splat PLY inside a spirula run directory."""
    checkpoints = [
        path
        for path in run_directory.glob("step-*.ckpt")
        if path.is_dir() and (path / "splat.ply").is_file()
    ]
    if not checkpoints:
        return None
    # The PLY is written inside each step-*.ckpt directory; with spirula's
    # default save_only_latest_checkpoint only the final one remains.
    return max(checkpoints, key=lambda path: path.name) / "splat.ply"
