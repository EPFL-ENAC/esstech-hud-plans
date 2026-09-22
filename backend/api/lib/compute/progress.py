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


class ColmapProgressEstimator:
    _PROCESSED = re.compile(r"Processed file \[(\d+)/(\d+)\]")
    _REGISTERED = re.compile(r"num_reg_frames=(\d+)")

    def __init__(self) -> None:
        self.total_images: int | None = None

    def feed(self, record: str) -> float | None:
        record = _ANSI_ESCAPE.sub("", record)
        if match := self._PROCESSED.search(record):
            self.total_images = int(match.group(2))
            progress = _fraction(int(match.group(1)), self.total_images)
            return None if progress is None else 0.30 * progress
        if "Feature matching & geometric verification" in record:
            return 0.35
        if match := self._REGISTERED.search(record):
            if self.total_images is not None:
                progress = _fraction(int(match.group(1)), self.total_images)
                if progress is not None:
                    return 0.40 + 0.60 * progress
        if "incremental_pipeline.cc" in record or "Registering image" in record:
            return 0.40
        return None


class BrushProgressEstimator:
    _STEPS = re.compile(r"(\d+)\s*/\s*(\d+)\s+Steps\b", re.IGNORECASE)

    def feed(self, record: str) -> float | None:
        match = self._STEPS.search(_ANSI_ESCAPE.sub("", record))
        if match is None:
            return None
        return _fraction(int(match.group(1)), int(match.group(2)))
