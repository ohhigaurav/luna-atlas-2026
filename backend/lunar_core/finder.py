"""Constraint-first landing-start-date search over precomputed visibility windows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import floor, isfinite

from lunar_core.events import VisibilityWindow
from lunar_core.metrics import AnalysisMetrics, compute_metrics


@dataclass(frozen=True, slots=True)
class SiteVisibilityWindows:
    site_id: str
    sun_windows: tuple[VisibilityWindow, ...]
    earth_windows: tuple[VisibilityWindow, ...]

    def __post_init__(self) -> None:
        if not self.site_id.strip():
            raise ValueError("site_id must not be empty")


@dataclass(frozen=True, slots=True)
class MissionProfile:
    mission_duration_s: float
    max_darkness_s: float | None
    max_dte_gap_s: float | None
    max_joint_outage_s: float | None
    min_sunlit_fraction: float | None

    def __post_init__(self) -> None:
        if not isfinite(self.mission_duration_s) or self.mission_duration_s <= 0:
            raise ValueError("mission_duration_s must be finite and positive")
        for name in ("max_darkness_s", "max_dte_gap_s", "max_joint_outage_s"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and non-negative, or None")
        if self.min_sunlit_fraction is not None and not 0.0 <= self.min_sunlit_fraction <= 1.0:
            raise ValueError("min_sunlit_fraction must be within [0, 1], or None")


@dataclass(frozen=True, slots=True)
class ConstraintFailure:
    constraint: str
    actual: float
    limit: float
    violation: float
    unit: str


@dataclass(frozen=True, slots=True)
class FinderCell:
    site_id: str
    start_s: float
    end_s: float
    feasible: bool
    first_failed_constraint: str | None
    failures: tuple[ConstraintFailure, ...]
    metrics: AnalysisMetrics


def candidate_start_times(
    start_min_s: float, start_max_s: float, step_s: float
) -> tuple[float, ...]:
    """Generate an inclusive, deterministic candidate-start grid."""
    if not all(isfinite(value) for value in (start_min_s, start_max_s, step_s)):
        raise ValueError("candidate range and step must be finite")
    if start_max_s < start_min_s:
        raise ValueError("start_max_s must be greater than or equal to start_min_s")
    if step_s <= 0:
        raise ValueError("step_s must be positive")
    count = floor((start_max_s - start_min_s) / step_s + 1e-12)
    return tuple(start_min_s + index * step_s for index in range(count + 1))


def evaluate_site_start(
    site: SiteVisibilityWindows, start_s: float, profile: MissionProfile
) -> FinderCell:
    """Evaluate one site/start-date cell; every outage already active at landing counts."""
    if not isfinite(start_s):
        raise ValueError("start_s must be finite")
    end_s = start_s + profile.mission_duration_s
    metrics = compute_metrics(
        site.sun_windows,
        site.earth_windows,
        interval_start_s=start_s,
        interval_end_s=end_s,
    )
    failures: list[ConstraintFailure] = []

    maximum_constraints = (
        ("max_darkness", metrics.longest_darkness.duration_s, profile.max_darkness_s, "s"),
        ("max_dte_gap", metrics.longest_dte_gap.duration_s, profile.max_dte_gap_s, "s"),
        ("max_joint_outage", metrics.longest_joint_outage.duration_s,
         profile.max_joint_outage_s, "s"),
    )
    for name, actual, limit, unit in maximum_constraints:
        if limit is not None and actual > limit:
            failures.append(ConstraintFailure(
                constraint=name, actual=actual, limit=limit,
                violation=actual - limit, unit=unit,
            ))
    if profile.min_sunlit_fraction is not None:
        actual = metrics.sunlit_fraction
        limit = profile.min_sunlit_fraction
        if actual < limit:
            failures.append(ConstraintFailure(
                constraint="min_sunlit_fraction", actual=actual, limit=limit,
                violation=limit - actual, unit="fraction",
            ))

    return FinderCell(
        site_id=site.site_id,
        start_s=start_s,
        end_s=end_s,
        feasible=not failures,
        first_failed_constraint=failures[0].constraint if failures else None,
        failures=tuple(failures),
        metrics=metrics,
    )


def evaluate_finder_grid(
    sites: Sequence[SiteVisibilityWindows],
    candidate_starts_s: Sequence[float],
    profile: MissionProfile,
) -> tuple[FinderCell, ...]:
    """Return a stable site-major grid. Sites and candidate dates are not silently reordered."""
    if not sites:
        raise ValueError("at least one site is required")
    if not candidate_starts_s:
        raise ValueError("at least one candidate start is required")
    site_ids = [site.site_id for site in sites]
    if len(set(site_ids)) != len(site_ids):
        raise ValueError("site IDs in finder input must be unique")
    if any(not isfinite(start) for start in candidate_starts_s):
        raise ValueError("candidate starts must be finite")
    if any(candidate_starts_s[i] >= candidate_starts_s[i + 1]
           for i in range(len(candidate_starts_s) - 1)):
        raise ValueError("candidate starts must be strictly increasing")
    return tuple(
        evaluate_site_start(site, start_s, profile)
        for site in sites
        for start_s in candidate_starts_s
    )
