"""Incremental progress estimates from command output, independent of workflows."""

import re
from collections.abc import Callable

type ReportProgress = Callable[[float], None]

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _fraction(current: float, total: float) -> float | None:
    if total <= 0:
        return None
    return min(max(current / total, 0.0), 1.0)


def _timestamp_seconds(timestamp: str) -> float:
    hours, minutes, seconds = map(float, timestamp.split(":"))
    return hours * 3600 + minutes * 60 + seconds


class FfmpegProgressEstimator:
    _TIMESTAMP = r"(\d+:\d{2}:\d{2}(?:\.\d+)?)"
    _DURATION = re.compile(r"Duration:\s*" + _TIMESTAMP)
    _POSITION = re.compile(r"time=\s*" + _TIMESTAMP)

    def __init__(self) -> None:
        self.duration_seconds: float | None = None

    def feed(self, record: str) -> float | None:
        record = _ANSI_ESCAPE.sub("", record)
        if match := self._DURATION.search(record):
            self.duration_seconds = _timestamp_seconds(match.group(1))
        if match := self._POSITION.search(record):
            if self.duration_seconds is not None:
                return _fraction(
                    _timestamp_seconds(match.group(1)), self.duration_seconds
                )
        return None


class SpirulaSfmProgressEstimator:
    _EXTRACTED = re.compile(r"^\s*(\d+)/(\d+)\s+\S+\s+Features:")
    _MATCHED = re.compile(r"(\d+)/(\d+) pairs matched")
    _IN_MODEL = re.compile(r"images in the model: (\d+)")

    def __init__(self) -> None:
        self.total_images: int | None = None

    def feed(self, record: str) -> float | None:
        record = _ANSI_ESCAPE.sub("", record)
        if match := self._EXTRACTED.match(record):
            self.total_images = int(match.group(2))
            progress = _fraction(int(match.group(1)), self.total_images)
            return None if progress is None else 0.25 * progress
        if match := self._MATCHED.search(record):
            progress = _fraction(int(match.group(1)), int(match.group(2)))
            return None if progress is None else 0.25 + 0.25 * progress
        if match := self._IN_MODEL.search(record):
            if self.total_images is not None:
                progress = _fraction(int(match.group(1)), self.total_images)
                if progress is not None:
                    return 0.50 + 0.50 * progress
            return 0.50
        return None


class SpirulaMaskProgressEstimator:
    _FRAME = re.compile(r"^\s*frame (\d+):")
    _SUMMARY = re.compile(r"^\s*frames: \d+ in ")

    def __init__(self, total_frames: int, pass_count: int) -> None:
        self.total_frames = total_frames
        self.pass_count = pass_count
        self.pass_index = 0
        self.progress = 0.0

    def _monotonic(self, progress: float) -> float:
        self.progress = max(self.progress, progress)
        return self.progress

    def feed(self, record: str) -> float | None:
        record = _ANSI_ESCAPE.sub("", record)
        if match := self._FRAME.match(record):
            frame_progress = _fraction(int(match.group(1)) + 1, self.total_frames)
            if frame_progress is None:
                return None
            return self._monotonic((self.pass_index + frame_progress) / self.pass_count)
        if self._SUMMARY.match(record):
            self.pass_index = min(self.pass_index + 1, self.pass_count)
            return self._monotonic(self.pass_index / self.pass_count)
        return None


class SpirulaTrainProgressEstimator:
    _STEPS = re.compile(r"step\s+\d+/(\d+)\s+\(\s*(\d+)%\)")

    def feed(self, record: str) -> float | None:
        record = _ANSI_ESCAPE.sub("", record)
        if match := self._STEPS.search(record):
            return _fraction(int(match.group(2)), 100)
        return None
