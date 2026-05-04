import os
import re

import cv2
from api.lib.compute.frame_picker import VideoAnalysis
from api.lib.types import ProgressCallback


def pick_frames(
    video_source_path: str,
    input_folder: str,
    output_folder: str,
    distance_threshold: float = 0.2,
    min_fps: int = 3,
    remove_outliers: bool = False,
    outlier_window_size: int = 5,
    outlier_sharpness_ratio: float = 0.5,
    on_progress: ProgressCallback | None = None,
):
    log = on_progress or (lambda msg, progress=None: print(f"[pick_frames] {msg}"))

    os.makedirs(output_folder, exist_ok=True)

    all_frames = [
        os.path.join(input_folder, f)
        for f in os.listdir(input_folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]

    all_frames.sort(key=lambda path: natural_keys(os.path.basename(path)))

    log(f"Collected and sorted {len(all_frames)} frames from {input_folder}")

    video = cv2.VideoCapture(video_source_path)
    if not video.isOpened():
        log(f"Warning: Could not open video {video_source_path}. Defaulting to 30 FPS.")
        fps = 30  # Default to 30 if we can't read the video
    else:
        fps = video.get(cv2.CAP_PROP_FPS)
        log(f"Video source FPS: {fps}")
    video.release()

    max_bin_length = max(int(fps / min_fps) if min_fps > 0 else 1, 1)
    log(f"Max bin length: {max_bin_length}")

    def progress_wrapper(msg: str, progress: float | None = None):
        log(
            msg, (progress * 0.9 + 0.05) if progress is not None else None
        )  # Scale progress to 5%-95% range

    video_analysis = VideoAnalysis.from_image_paths(
        all_frames,
        distance_threshold=distance_threshold,
        max_bin_size=max_bin_length,
        remove_outliers=remove_outliers,
        outlier_window_size=outlier_window_size,
        outlier_sharpness_ratio=outlier_sharpness_ratio,
        on_progress=progress_wrapper,
    )

    video_analysis.export_to_folders(input_folder)

    picked_frames = video_analysis.export_best_frames(
        output_folder, on_progress=on_progress
    )

    log(
        f"Selected {len(picked_frames)}/{len(all_frames)} frames after evaluation ({len(picked_frames) / len(all_frames):.2%})."
    )

    return picked_frames


def natural_keys(text):
    """
    alist.sort(key=natural_keys) sorts in human order
    http://nedbatchelder.com/blog/200712/human_sorting.html
    """
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", text)]
