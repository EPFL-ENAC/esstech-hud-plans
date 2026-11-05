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


class SpirulaTrainProgressEstimator:
    _STEPS = re.compile(r"step\s+\d+/(\d+)\s+\(\s*(\d+)%\)")

    def feed(self, record: str) -> float | None:
        record = _ANSI_ESCAPE.sub("", record)
        if match := self._STEPS.search(record):
            return _fraction(int(match.group(2)), 100)
        return None
