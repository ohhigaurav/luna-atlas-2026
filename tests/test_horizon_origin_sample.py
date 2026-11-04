"""Regression: the ground sample under the observer must never become the horizon (bug found 2026-11-04).

At observer height 0 the distance-0 sample has apparent elevation atan2(dh, 0) with dh ~ 1e-9 m of
rounding: +90 deg if dh > 0, which blocked the whole sky at that point.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from lunar_core.terrain import HORIZON_ALGORITHM_VERSION, horizon_bins_from_samples

R = 1_737_400.0


def _grid(ground: float, origin_error: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    distances = np.array([0.0, 5.0, 10.0, 1_000.0, 200_000.0])
    azimuths = np.arange(0.0, 360.0, 90.0)
    heights = np.tile(np.array([ground + origin_error, ground, ground - 1.0, ground + 10.0, ground]), (4, 1))
    return heights, distances, azimuths


@pytest.mark.parametrize("origin_error", [1e-9, -1e-9, 0.0])
def test_origin_rounding_never_becomes_the_horizon_at_zero_height(origin_error: float) -> None:
    heights, distances, azimuths = _grid(1234.5, origin_error)
    bins = horizon_bins_from_samples(heights, distances, azimuths, reference_radius_m=R,
                                     observer_radius_m=R + 1234.5, max_range_m=200_000.0)
    for b in bins:
        # the 10 m rise at 1 km controls: ~0.57 deg, never +/-90 or the 0-deg 0/0 case
        assert b.controlling_distance_m == 1_000.0
        assert math.degrees(b.elevation_rad) == pytest.approx(math.degrees(math.atan2(10.0, 1_000.0)), abs=0.05)
        assert b.coverage_status == "complete"


def test_unchanged_for_an_observer_above_the_ground() -> None:
    heights, distances, azimuths = _grid(1234.5, 0.0)
    obs = R + 1234.5 + 2.0
    bins = horizon_bins_from_samples(heights, distances, azimuths, reference_radius_m=R,
                                     observer_radius_m=obs, max_range_m=200_000.0)
    # the pre-fix formula (origin included) for comparison
    radii = R + heights
    ang = distances[None, :] / R
    old = np.arctan2(radii * np.cos(ang) - obs, radii * np.sin(ang)).max(axis=1)
    assert [b.elevation_rad for b in bins] == pytest.approx(old.tolist())


def test_only_origin_known_is_no_horizon_and_version_bumped() -> None:
    heights = np.array([[100.0, np.nan, np.nan]])
    bins = horizon_bins_from_samples(heights, np.array([0.0, 5.0, 200_000.0]), np.array([0.0]),
                                     reference_radius_m=R, observer_radius_m=R + 100.0, max_range_m=200_000.0)
    assert bins[0].elevation_rad is None and bins[0].coverage_status == "none"
    assert HORIZON_ALGORITHM_VERSION == "terrain-horizon-2.2-no-origin-sample"
