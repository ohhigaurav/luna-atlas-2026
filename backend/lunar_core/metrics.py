"""Duration metrics derived from refined visibility windows, never coarse samples."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import median

from lunar_core.events import VisibilityWindow


@dataclass(frozen=True, slots=True)
class OutageMetric:
    duration_s: float
    truncated_start: bool
    truncated_end: bool

    @property
    def truncated(self) -> bool:
        return self.truncated_start or self.truncated_end

    @property
    def display_duration_s(self) -> float:
        """The reported value is a lower bound when the interval edge truncates the outage."""
        return self.duration_s


@dataclass(frozen=True, slots=True)
class AnalysisMetrics:
    interval_duration_s: float
    sunlit_fraction: float
    dte_clear_fraction: float
    both_fraction: float
    joint_outage_fraction: float
    longest_darkness: OutageMetric
    longest_dte_gap: OutageMetric
    longest_joint_outage: OutageMetric
    sun_window_count: int
    median_sun_window_s: float | None


def _normalise_intervals(
    windows: Iterable[VisibilityWindow], start_s: float, end_s: float
) -> list[tuple[float, float]]:
    clipped = sorted(
        (max(start_s, w.start_s), min(end_s, w.end_s))
        for w in windows
        if w.end_s > start_s and w.start_s < end_s and w.end_s > w.start_s
    )
    merged: list[tuple[float, float]] = []
    for left, right in clipped:
        if right <= left:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged


def _duration(intervals: Sequence[tuple[float, float]]) -> float:
    return sum(right - left for left, right in intervals)


def _intersection(
    first: Sequence[tuple[float, float]], second: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    i = j = 0
    while i < len(first) and j < len(second):
        left = max(first[i][0], second[j][0])
        right = min(first[i][1], second[j][1])
        if right > left:
            result.append((left, right))
        if first[i][1] < second[j][1]:
            i += 1
        else:
            j += 1
    return result


def _union(
    first: Sequence[tuple[float, float]], second: Sequence[tuple[float, float]]
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for left, right in sorted([*first, *second]):
        if result and left <= result[-1][1]:
            result[-1] = (result[-1][0], max(result[-1][1], right))
        elif right > left:
            result.append((left, right))
    return result


def _complement(
    intervals: Sequence[tuple[float, float]], start_s: float, end_s: float
) -> list[tuple[float, float]]:
    outages: list[tuple[float, float]] = []
    cursor = start_s
    for left, right in intervals:
        left = max(start_s, left)
        right = min(end_s, right)
        if left > cursor:
            outages.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end_s:
        outages.append((cursor, end_s))
    return outages


def _longest_outage(
    intervals: Sequence[tuple[float, float]], start_s: float, end_s: float
) -> OutageMetric:
    if not intervals:
        return OutageMetric(duration_s=0.0, truncated_start=False, truncated_end=False)
    longest_duration = max(right - left for left, right in intervals)
    epsilon = max(1e-9, (end_s - start_s) * 1e-12)
    longest_intervals = [
        (left, right) for left, right in intervals
        if abs((right - left) - longest_duration) <= epsilon
    ]
    # If equal longest outages touch opposite interval edges, both truncation flags matter even
    # though no single interval touches both edges.
    return OutageMetric(
        duration_s=longest_duration,
        truncated_start=any(abs(left - start_s) <= epsilon for left, _ in longest_intervals),
        truncated_end=any(abs(right - end_s) <= epsilon for _, right in longest_intervals),
    )


def compute_metrics(
    sun_windows: Sequence[VisibilityWindow],
    earth_windows: Sequence[VisibilityWindow],
    *,
    interval_start_s: float,
    interval_end_s: float,
) -> AnalysisMetrics:
    """Compute PRD SR-08 metrics over a requested interval.

    Windows are clipped to the requested interval. Window overlap is normalised defensively,
    and the requested interval duration is the denominator for every fraction.
    """
    if interval_end_s <= interval_start_s:
        raise ValueError("interval_end_s must be greater than interval_start_s")
    duration = interval_end_s - interval_start_s
    sun = _normalise_intervals(sun_windows, interval_start_s, interval_end_s)
    earth = _normalise_intervals(earth_windows, interval_start_s, interval_end_s)
    both = _intersection(sun, earth)
    any_visible = _union(sun, earth)
    joint_outages = _complement(any_visible, interval_start_s, interval_end_s)
    sun_outages = _complement(sun, interval_start_s, interval_end_s)
    earth_outages = _complement(earth, interval_start_s, interval_end_s)
    sun_durations = [right - left for left, right in sun]

    return AnalysisMetrics(
        interval_duration_s=duration,
        sunlit_fraction=_duration(sun) / duration,
        dte_clear_fraction=_duration(earth) / duration,
        both_fraction=_duration(both) / duration,
        joint_outage_fraction=_duration(joint_outages) / duration,
        longest_darkness=_longest_outage(sun_outages, interval_start_s, interval_end_s),
        longest_dte_gap=_longest_outage(earth_outages, interval_start_s, interval_end_s),
        longest_joint_outage=_longest_outage(joint_outages, interval_start_s, interval_end_s),
        sun_window_count=len(sun),
        median_sun_window_s=median(sun_durations) if sun_durations else None,
    )
