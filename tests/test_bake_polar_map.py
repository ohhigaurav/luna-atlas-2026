from __future__ import annotations

import math

import numpy as np
import pytest

from tools import bake_polar_map as bake


def test_grid_is_square_centred_and_north_first() -> None:
    n, pts = bake.grid(100, 4)
    assert n == 51 and len(pts) == 51 * 51
    assert pts[0] == (-100_000.0, 100_000.0) and pts[-1] == (100_000.0, -100_000.0)
    assert pts[25 * 51 + 25] == (0.0, 0.0)


def test_daily_percent() -> None:
    flags = [True] * 12 + [False] * 12 + [True] * 24 + [False]  # 2 days + closing sample
    assert bake.daily_percent(flags, 24, 2) == [50, 100]


def test_margins_flat_horizon_matches_elevation() -> None:
    # Body straight up at the equator / lon 0 -> elevation 90 deg; on the horizon to the east -> 0 deg.
    az = np.arange(0, 360, 0.5)
    flat = np.zeros_like(az)
    unit = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    dist = np.array([1e9, 1e9])
    m = bake.margins(unit, dist, 0.0, 0.0, 1_737_400.0, az, flat, add_semidiameter=False)
    assert m[0] == pytest.approx(math.pi / 2, abs=1e-6)
    assert m[1] == pytest.approx(0.0, abs=2e-6)
    with_sd = bake.margins(unit, dist, 0.0, 0.0, 1_737_400.0, az, flat, add_semidiameter=True, body_radius_m=1e6)
    assert with_sd[1] - m[1] == pytest.approx(math.asin(1e6 / 1e12), rel=1e-3)
