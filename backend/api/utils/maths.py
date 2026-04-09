import math
import statistics
from dataclasses import dataclass


def safe_mean(values: list[int] | list[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def safe_median(values: list[int] | list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def percentile(values: list[float], q: float) -> float:
    return (
        _percentile_from_sorted_values(sorted(float(v) for v in values), q)
        if values
        else 0.0
    )


def _percentile_from_sorted_values(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        return 0.0
    if q <= 0:
        return float(sorted_values[0])
    if q >= 100:
        return float(sorted_values[-1])

    pos = (len(sorted_values) - 1) * (q / 100.0)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def fraction_leq(values: list[float], threshold: float) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if v <= threshold) / len(values)


def contiguous_segments(indices: list[int]) -> list[tuple[int, int]]:
    """
    Find contiguous segments in a list of integers.
    For example, given [1, 2, 3, 5, 6, 10], it would return [(1, 3), (5, 6), (10, 10)].
    """
    if not indices:
        return []

    sorted_unique = sorted(set(indices))
    segments = []

    start = sorted_unique[0]
    prev = sorted_unique[0]

    for x in sorted_unique[1:]:
        if x == prev + 1:
            prev = x
        else:
            segments.append((start, prev))
            start = x
            prev = x

    segments.append((start, prev))
    return segments


def clamp01(value: float) -> float:
    """Clamp a value to the range [0, 1]."""
    return max(0.0, min(1.0, value))


@dataclass
class MeanMedianMinMax:
    mean: float | None
    median: float | None
    min: float | None
    max: float | None

    @staticmethod
    def from_values(values: list[int] | list[float]) -> "MeanMedianMinMax":
        if len(values) == 0:
            return MeanMedianMinMax(mean=None, median=None, min=None, max=None)

        return MeanMedianMinMax(
            mean=statistics.mean(values),
            median=safe_median(values),
            min=float(min(values)) if values else 0.0,
            max=float(max(values)) if values else 0.0,
        )


@dataclass
class StatisticsSummary:
    mean: float | None
    median: float | None
    p90: float | None
    p95: float | None

    @staticmethod
    def from_values(values: list[int] | list[float]) -> "StatisticsSummary":
        if len(values) == 0:
            return StatisticsSummary(mean=None, median=None, p90=None, p95=None)

        sorted_values = sorted(float(v) for v in values)

        return StatisticsSummary(
            mean=statistics.mean(values),
            median=safe_median(values),
            p90=_percentile_from_sorted_values(sorted_values, 90.0),
            p95=_percentile_from_sorted_values(sorted_values, 95.0),
        )
