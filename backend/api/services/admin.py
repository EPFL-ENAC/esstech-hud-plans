import json
import os
from datetime import datetime

import pandas as pd

backend_root = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
splats_dir = os.path.join(backend_root, "data", "splats")


def parse_timestamp(ts: str | None) -> datetime | None:
    """Parse ISO timestamp string to datetime object."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def calculate_duration_seconds(start: str | None, end: str | None) -> float | None:
    """Calculate duration in seconds between two timestamps."""
    if not start or not end:
        return None
    start_dt = parse_timestamp(start)
    end_dt = parse_timestamp(end)
    if start_dt and end_dt:
        return (end_dt - start_dt).total_seconds()
    return None


def flatten_status_data(status_file_path: str) -> dict:
    """Extract and flatten all relevant data from a status.json file."""
    try:
        with open(status_file_path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Error reading {status_file_path}: {e}")
        return {}

    generation_id = data.get("name", "")
    overall_status = data.get("overall_status", "")
    video_path = data.get("settings", {}).get("video_path", "")
    started_at = data.get("started_at")
    finished_at = data.get("finished_at")

    row = {
        "generation_id": generation_id,
        "overall_status": overall_status,
        "video_path": video_path,
        "started_at": started_at,
        "finished_at": finished_at,
        "total_time_seconds": calculate_duration_seconds(started_at, finished_at),
    }

    settings = data.get("settings", {}) or {}

    ffmpeg_settings = settings.get("ffmpeg") or {}
    row["ffmpeg_fps"] = ffmpeg_settings.get("fps")
    row["ffmpeg_fitInWidth"] = ffmpeg_settings.get("fitInWidth")
    row["ffmpeg_fitInHeight"] = ffmpeg_settings.get("fitInHeight")

    colmap_settings = settings.get("colmap") or {}
    row["colmap_data_type"] = colmap_settings.get("data_type")
    row["colmap_quality"] = colmap_settings.get("quality")
    row["colmap_camera_model"] = colmap_settings.get("camera_model")
    row["colmap_max_image_size"] = colmap_settings.get("max_image_size")
    row["colmap_single_camera"] = colmap_settings.get("single_camera")
    row["colmap_dense"] = colmap_settings.get("dense")

    brush_settings = settings.get("brush", {})
    row["brush_totalSteps"] = brush_settings.get("totalSteps")
    row["brush_renderMode"] = brush_settings.get("renderMode")
    row["brush_shDegree"] = brush_settings.get("shDegree")
    row["brush_maxSplats"] = brush_settings.get("maxSplats")
    row["brush_growthGradThreshold"] = brush_settings.get("growthGradThreshold")
    row["brush_refineEvery"] = brush_settings.get("refineEvery")
    row["brush_growthStopIter"] = brush_settings.get("growthStopIter")
    row["brush_alphaMode"] = brush_settings.get("alphaMode")
    row["brush_maxResolution"] = brush_settings.get("maxResolution")
    row["brush_subsampleFrames"] = brush_settings.get("subsampleFrames")

    # blueprint_settings = settings.get("blueprint")
    # if blueprint_settings:
    #     row["blueprint_enabled"] = blueprint_settings.get("enabled")
    #     row["blueprint_imageWidth"] = blueprint_settings.get("imageWidth")
    #     row["blueprint_imageHeight"] = blueprint_settings.get("imageHeight")
    #     row["blueprint_radiusScale"] = blueprint_settings.get("radiusScale")
    #     row["blueprint_verticalClip"] = blueprint_settings.get("verticalClip")
    #     row["blueprint_opacityShift"] = blueprint_settings.get("opacityShift")
    #     row["blueprint_opacity"] = blueprint_settings.get("opacity")
    # else:
    #     row["blueprint_enabled"] = None
    #     row["blueprint_imageWidth"] = None
    #     row["blueprint_imageHeight"] = None
    #     row["blueprint_radiusScale"] = None
    #     row["blueprint_verticalClip"] = None
    #     row["blueprint_opacity"] = None

    interactive_params = data.get("interactive_blueprint_params")
    if interactive_params:
        row["interactive_viewerSize"] = interactive_params.get("viewerSize")
        row["interactive_sceneZRotation"] = interactive_params.get("sceneZRotation")
        row["interactive_displayCameraPositions"] = interactive_params.get(
            "displayCameraPositions"
        )
        row["interactive_displayFloor"] = interactive_params.get("displayFloor")
        row["interactive_floorZOffset"] = interactive_params.get("floorZOffset")
        row["interactive_cameramanHeightCm"] = interactive_params.get(
            "cameramanHeightCm"
        )
        section_z_factor = interactive_params.get("sectionZFactor")
        if section_z_factor:
            row["interactive_sectionZFactor_min"] = section_z_factor.get("min")
            row["interactive_sectionZFactor_max"] = section_z_factor.get("max")
        else:
            row["interactive_sectionZFactor_min"] = None
            row["interactive_sectionZFactor_max"] = None
        row["interactive_densityThreshold"] = interactive_params.get("densityThreshold")
        row["interactive_opacityMultiplier"] = interactive_params.get(
            "opacityMultiplier"
        )
        row["interactive_contrast"] = interactive_params.get("contrast")
    else:
        row["interactive_viewerSize"] = None
        row["interactive_sceneZRotation"] = None
        row["interactive_displayCameraPositions"] = None
        row["interactive_displayFloor"] = None
        row["interactive_floorZOffset"] = None
        row["interactive_cameramanHeightCm"] = None
        row["interactive_sectionZFactor_min"] = None
        row["interactive_sectionZFactor_max"] = None
        row["interactive_densityThreshold"] = None
        row["interactive_opacityMultiplier"] = None
        row["interactive_contrast"] = None

    generation_feedback = data.get("generation_feedback")
    if generation_feedback:
        ratings = generation_feedback.get("ratings", [])
        colmap_rating = next(
            (r["rating"] for r in ratings if r["category"] == "colmap"), None
        )
        splats_rating = next(
            (r["rating"] for r in ratings if r["category"] == "splats"), None
        )
        blueprint_rating = next(
            (r["rating"] for r in ratings if r["category"] == "blueprint"), None
        )
        row["feedback_colmap_rating"] = colmap_rating
        row["feedback_splats_rating"] = splats_rating
        row["feedback_blueprint_rating"] = blueprint_rating
        row["feedback_notes"] = generation_feedback.get("notes", "")
    else:
        row["feedback_colmap_rating"] = None
        row["feedback_splats_rating"] = None
        row["feedback_blueprint_rating"] = None
        row["feedback_notes"] = None

    steps = data.get("steps", {})

    ffmpeg_step = steps.get("ffmpeg", {})
    ffmpeg_started = ffmpeg_step.get("started_at")
    ffmpeg_finished = ffmpeg_step.get("finished_at")
    row["ffmpeg_time_seconds"] = calculate_duration_seconds(
        ffmpeg_started, ffmpeg_finished
    )

    colmap_step = steps.get("colmap", {})
    colmap_started = colmap_step.get("started_at")
    colmap_finished = colmap_step.get("finished_at")
    row["colmap_time_seconds"] = calculate_duration_seconds(
        colmap_started, colmap_finished
    )

    brush_step = steps.get("brush", {})
    brush_started = brush_step.get("started_at")
    brush_finished = brush_step.get("finished_at")
    row["brush_time_seconds"] = calculate_duration_seconds(
        brush_started, brush_finished
    )

    blueprint_step = steps.get("blueprint_extraction", {})
    blueprint_started = blueprint_step.get("started_at")
    blueprint_finished = blueprint_step.get("finished_at")
    row["blueprint_extraction_time_seconds"] = calculate_duration_seconds(
        blueprint_started, blueprint_finished
    )

    return row


def generate_parameters_table() -> tuple[list[dict], str]:
    """
    Generate parameters table from all status.json files.

    Scans all status.json files in data/splats/<gen-id>/ directories and
    aggregates generation IDs, tool settings (ffmpeg, colmap, brush),
    video path, interactive blueprint params, generation feedback, and timing data.

    Returns:
        tuple: (list of row dicts, filename for download)
    """
    if not os.path.exists(splats_dir):
        raise FileNotFoundError("Splats directory not found")

    rows = []
    for generation_id in os.listdir(splats_dir):
        generation_dir = os.path.join(splats_dir, generation_id)
        if not os.path.isdir(generation_dir):
            continue

        status_file = os.path.join(generation_dir, "status.json")
        if not os.path.exists(status_file):
            continue

        row_data = flatten_status_data(status_file)
        if row_data:
            rows.append(row_data)

    if not rows:
        raise FileNotFoundError("No generation data found")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"parameters_table_{timestamp}.xlsx"

    return rows, filename
