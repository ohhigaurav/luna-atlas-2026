from __future__ import annotations

import numpy as np
import pytest

from tools import compare_goddard_maps as g


def test_disc_fraction_limits_and_half() -> None:
    sd = np.full(5, 0.01)
    f = g.disc_fraction(np.array([-0.02, -0.01, 0.0, 0.01, 0.02]), sd)
    assert f.tolist() == pytest.approx([0.0, 0.0, 0.5, 1.0, 1.0])
    quarter = g.disc_fraction(np.array([0.005]), np.array([0.01]))[0]
    assert 0.5 < quarter < 1.0 and quarter == pytest.approx(0.8045, abs=1e-3)


def test_physical_scaling_from_labels() -> None:
    assert g.physical(np.array([25000, 0], dtype=np.int16), "sun").tolist() == pytest.approx([1.0, 0.0])
    assert g.physical(np.array([20000, -20000], dtype=np.int16), "psr").tolist() == pytest.approx([1.0, 0.0])
    assert g.physical(np.array([0.3], dtype=np.float32), "sun").tolist() == pytest.approx([0.3])


def test_draw_is_stratified_smooth_and_near_the_pole() -> None:
    n = 200
    col_x = (np.arange(n) - n / 2 + 0.5) * 1000.0      # 1 km pixels, +/-100 km
    row_y = -(np.arange(n) - n / 2 + 0.5) * 1000.0
    xx, yy = np.meshgrid(col_x, row_y)
    sun = np.clip(np.hypot(xx, yy) / 100_000.0, 0, 1)  # smooth ramp outward
    picks = g.draw(sun, row_y, col_x)
    assert picks == g.draw(sun, row_y, col_x)
    for r, c, k in picks:
        assert np.hypot(col_x[c], row_y[r]) <= g.RADIUS_KM * 1000.0
        lo, hi = g.STRATA[k]
        assert lo <= sun[r, c] < hi
    assert {k for _r, _c, k in picks} == {0, 1, 2, 3}  # ramp reaches 0.6 only beyond 60 km


def test_judge() -> None:
    j = g.judge([0.1, 0.2, 0.3, 0.4], [0.1, 0.25, 0.3, 0.45])
    assert j["median_diff"] == pytest.approx(-0.025) and j["share_within"] == 1.0 and j["pass"] is True
