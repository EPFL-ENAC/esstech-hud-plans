import os
from collections import deque
from collections.abc import Iterable, Iterator

from api.lib.types import ProgressCallback

from .video_frame import VideoFrame


class ImageBin:
    images: list[VideoFrame]

    def __init__(self, images: list[VideoFrame] | None = None):
        if images is not None:
            self.images = images
        else:
            self.images = []

    def get_bin_name(self) -> str:
        if not self.images or len(self.images) == 0:
            return "empty_bin"

        return f"{self.images[0].name} ({len(self.images)})"

    def add_if_similar(
        self,
        image: VideoFrame,
        threshold: float = 0.3,
        max_bin_size: int = 10,
        outstanding_quality_mark: float = 0.9,
        on_progress: ProgressCallback | None = None,
    ) -> bool:
        log = on_progress or (
            lambda msg, progress=None: print(f"[ImageBin.add_if_similar] {msg}")
        )

        if not self.images:
            self.images.append(image)
            return True

        if len(self.images) >= max_bin_size:
            log(f"[{self.get_bin_name()}] Bin is full")
            return False

        representative = self.images[0]
        dist = representative.distance(image).changes_score_smart

        if dist >= threshold:
            log(
                f"[{self.get_bin_name()}] Rejected {image.name}: "
                f"distance {dist:.3f} >= threshold {threshold:.3f}"
            )
            return False

        _, best_quality = self.best_image()
        already_has_outstanding = best_quality >= outstanding_quality_mark
        is_outstanding = image.overall_sharpness >= outstanding_quality_mark

        if is_outstanding and already_has_outstanding:
            log(
                f"[{self.get_bin_name()}] Rejected {image.name}: "
                f"bin already has an outstanding frame"
            )
            return False

        self.images.append(image)
        log(f"[{self.get_bin_name()}] Added {image.name}")
        return True

    def best_image(self) -> tuple[VideoFrame, float]:
        best = self.images[0]
        best_score = best.overall_sharpness

        for img in self.images:
            score = img.overall_sharpness
            if score > best_score:
                best_score = score
                best = img

        return best, best_score


class VideoAnalysis:
    bins: list[ImageBin]

    def __init__(self):
        self.bins = []

    def add_image(
        self,
        image: VideoFrame,
        threshold: float = 0.3,
        max_bin_size: int = 10,
        on_progress: ProgressCallback | None = None,
    ):
        log = on_progress or (
            lambda msg, progress=None: print(f"[VideoAnalysis.add_image] {msg}")
        )

        last_bin = self.bins[-1] if self.bins else None

        if last_bin is None or not last_bin.add_if_similar(
            image,
            threshold=threshold,
            max_bin_size=max_bin_size,
            on_progress=on_progress,
        ):
            new_bin = ImageBin(images=[image])
            self.bins.append(new_bin)

            log(
                f"[{new_bin.get_bin_name()}] Created new bin with {image.name} (total bins: {len(self.bins)})"
            )

    @staticmethod
    def _iter_frames(
        paths: Iterable[str],
        *,
        thumbnail_size: int = 64,
        on_progress: ProgressCallback | None = None,
    ) -> Iterator[VideoFrame]:
        log = on_progress or (lambda msg: print(f"[VideoAnalysis._iter_frames] {msg}"))

        for index, path in enumerate(paths):
            try:
                yield VideoFrame.from_file(path, index, thumbnail_size=thumbnail_size)
            except Exception as e:
                log(f"Warning: Failed to analyze image at {path}: {e}")

    @staticmethod
    def _iter_frames_without_outliers(
        paths: Iterable[str],
        *,
        thumbnail_size: int = 64,
        outlier_window_size: int = 5,
        outlier_sharpness_ratio: float = 0.5,
        on_progress: ProgressCallback | None = None,
    ) -> Iterator[VideoFrame]:
        log = on_progress or (lambda msg: print(f"[Outlier Removal] {msg}"))

        if outlier_window_size < 3:
            raise ValueError("outlier_window_size must be >= 3")
        if outlier_window_size % 2 == 0:
            raise ValueError("outlier_window_size must be odd")

        log(
            f"Starting outlier removal with window size {outlier_window_size} and sharpness ratio {outlier_sharpness_ratio}"
        )

        half_window = outlier_window_size // 2
        window: deque[VideoFrame] = deque()
        sharpness_sum = 0.0
        emitted_leading_edges = False
        outliers_removed = 0

        for index, path in enumerate(paths):
            try:
                frame = VideoFrame.from_file(path, index, thumbnail_size=thumbnail_size)
            except Exception as e:
                log(f"Warning: Failed to analyze image at {path}: {e}")
                continue

            window.append(frame)
            sharpness_sum += frame.overall_sharpness

            if len(window) < outlier_window_size:
                log(f"Window too small: {len(window)}/{outlier_window_size}")
                continue

            if not emitted_leading_edges:
                for edge_frame in list(window)[:half_window]:
                    yield edge_frame
                emitted_leading_edges = True

            center = window[half_window]
            others_avg = (sharpness_sum - center.overall_sharpness) / (
                outlier_window_size - 1
            )

            is_outlier = (
                others_avg > 0.0
                and center.overall_sharpness < outlier_sharpness_ratio * others_avg
            )

            if is_outlier:
                outliers_removed += 1
                log(
                    f"Skipping outlier {center.name}: "
                    f"sharpness={center.overall_sharpness:.4f}, "
                    f"neighbors_avg={others_avg:.4f}, "
                    f"ratio={outlier_sharpness_ratio:.4f}"
                )
                log(f"Total outliers removed so far: {outliers_removed}")
            else:
                yield center

            oldest = window.popleft()
            sharpness_sum -= oldest.overall_sharpness

        if not emitted_leading_edges:
            while window:
                yield window.popleft()
            return

        trailing_frames = list(window)[-half_window:]
        for frame in trailing_frames:
            yield frame

    @staticmethod
    def from_image_paths(
        paths: list[str],
        distance_threshold: float = 0.3,
        max_bin_size: int = 10,
        remove_outliers: bool = True,
        outlier_window_size: int = 5,
        outlier_sharpness_ratio: float = 0.5,
        on_progress: ProgressCallback | None = None,
    ) -> "VideoAnalysis":
        log = on_progress or (
            lambda msg, progress=None: print(
                f"[VideoAnalysis.from_image_paths] {msg} {progress:.2%}"
                if progress is not None
                else f"[VideoAnalysis.from_image_paths] {msg}"
            )
        )

        analysis = VideoAnalysis()

        if remove_outliers:
            frames_iter = VideoAnalysis._iter_frames_without_outliers(
                paths,
                thumbnail_size=64,
                outlier_window_size=outlier_window_size,
                outlier_sharpness_ratio=outlier_sharpness_ratio,
                on_progress=on_progress,
            )
        else:
            frames_iter = VideoAnalysis._iter_frames(
                paths, thumbnail_size=64, on_progress=on_progress
            )

        for frame in frames_iter:
            progress = frame.index / len(paths)
            log(f"Processing frame: {frame.name}", progress)
            analysis.add_image(
                frame,
                threshold=distance_threshold,
                max_bin_size=max_bin_size,
                on_progress=on_progress,
            )

        return analysis

    def export_to_folders(
        self, output_folder: str, symlink_relative_to: str | None = None
    ):
        os.makedirs(output_folder, exist_ok=True)
        for i, bin in enumerate(self.bins):
            bin_folder = os.path.join(output_folder, f"bin_{i}")
            os.makedirs(bin_folder, exist_ok=True)
            for image in bin.images:
                dst = os.path.join(bin_folder, image.name)

                src = image.full_path
                if symlink_relative_to:
                    # Calculate the source path relative to the destination directory
                    src = os.path.relpath(image.full_path, bin_folder)

                if os.path.lexists(dst):
                    os.remove(dst)
                os.symlink(src, dst)

    def export_best_frames(
        self,
        output_folder: str,
        on_progress: ProgressCallback | None = None,
        symlink_relative_to: str | None = None,
    ):
        log = on_progress or (
            lambda msg: print(f"[VideoAnalysis.export_best_frames] {msg}")
        )

        best_images = [bin.best_image() for bin in self.bins]
        os.makedirs(output_folder, exist_ok=True)

        final_images = []

        for image, score in best_images:
            log(
                f"Best image in bin: {image.name} with COLMAP score: "
                f"{score:.4f} (overall sharpness: {image.overall_sharpness:.4f})"
            )
            dst = os.path.join(output_folder, image.name)

            src = image.full_path
            if symlink_relative_to:
                # Calculate the source path relative to the destination directory
                src = os.path.relpath(image.full_path, output_folder)

            if os.path.lexists(dst):
                os.remove(dst)
            os.symlink(src, dst)

            final_images.append(image)

        return final_images
