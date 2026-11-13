"""Sunlight power (power.py): analytic cases whose answers follow from the formula alone.

Expected values written before the code was run:
  full disc, Sun on the horizontal plane, 1 AU      -> vertical 1361, flat 0
  full disc, Sun 30 deg high, 1 AU                  -> vertical 1361 cos 30 = 1178.66, flat 680.5
  full disc, Sun on the horizontal plane, 1.0167 AU -> 1361 / 1.0167^2 = 1316.6
  disc centre exactly on the horizon edge           -> half the disc, 680.5 on a vertical panel
"""

from __future__ import annotations

import math

import pytest
from lunar_core import compare, power

AU = power.AU_M


def row(et: float, el: float, horizon: float, r: float = AU, utc: str | None = None) -> dict:
    return {"et_s": et, "utc": utc or f"t{et:g}", "sun_elevation_deg": el, "sun_horizon_deg": horizon,
            "sun_range_m": r}


def test_full_disc_on_the_horizontal_plane_at_1_au():
    s = power.sample_power(row(0, 0.0, -5.0))
    assert s["disc_fraction"] == 1.0
    assert s["vertical_w_m2"] == pytest.approx(1361.0)
    assert s["horizontal_w_m2"] == 0.0


def test_sun_30_degrees_high():
    s = power.sample_power(row(0, 30.0, 0.0))
    assert s["vertical_w_m2"] == pytest.approx(1361.0 * math.cos(math.radians(30)))
    assert s["horizontal_w_m2"] == pytest.approx(680.5)


def test_inverse_square_distance():
    assert power.sample_power(row(0, 0.0, -5.0, r=1.0167 * AU))["vertical_w_m2"] == pytest.approx(1316.6, abs=0.1)


def test_half_disc_when_the_centre_sits_on_the_horizon():
    s = power.sample_power(row(0, 1.0, 1.0))
    assert s["disc_fraction"] == pytest.approx(0.5)
    assert s["vertical_w_m2"] == pytest.approx(0.5 * 1361.0 * math.cos(math.radians(1.0)))


def test_sun_below_horizon_gives_nothing():
    s = power.sample_power(row(0, 0.5, 2.0))
    assert s["disc_fraction"] == 0.0 and s["vertical_w_m2"] == 0.0


STEP = 1800.0


def slow_sunrise(n_dark: int = 2, n_rise: int = 6, n_full: int = 4) -> tuple[list[dict], list[dict]]:
    """Horizon at 1 deg; the Sun centre climbs 0.1 deg per step through it (a polar-style sunrise)."""
    series, el = [], 1.0 - 0.27 - 0.2 * n_dark
    for i in range(n_dark + n_rise + n_full):
        series.append(row(i * STEP, el, 1.0))
        el += 0.1 if i >= n_dark else 0.2
    return series, []


def test_first_sunrise_time_to_full_disc_from_the_refined_event():
    series = [row(i * STEP, el, 1.0) for i, el in enumerate([0.0, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6])]
    # upper limb clears at 0.733 deg (1 - 0.267 semidiameter): between steps 1 and 2; event at 2700 s
    windows = [{"start_et_s": 2700.0, "end_et_s": 99999.0, "start_utc": "rise", "end_utc": "x",
                "start_truncated": False, "end_truncated": True}]
    out = power.summarise(series, windows)
    fr = out["first_sunrise"]
    first_full = next(i for i, r in enumerate(series)
                      if power.sample_power(r)["disc_fraction"] >= power.FULL_DISC)
    assert fr["full_disc_reached"] and not fr["lower_bound"]
    assert fr["to_full_disc_h"] == pytest.approx((first_full * STEP - 2700.0) / 3600.0)
    assert fr["resolution_h"] == 0.5
    assert 0 < out["partial_sun_percent"] < 100


def test_sunrise_cut_by_the_end_of_the_period_is_a_lower_bound():
    series = [row(i * STEP, el, 1.0) for i, el in enumerate([0.0, 0.6, 0.8, 0.9])]
    windows = [{"start_et_s": 2700.0, "end_et_s": 3 * STEP, "start_utc": "rise", "end_utc": "x",
                "start_truncated": False, "end_truncated": True}]
    fr = power.summarise(series, windows)["first_sunrise"]
    assert fr["lower_bound"] and not fr["full_disc_reached"]
    assert fr["to_full_disc_h"] == pytest.approx((3 * STEP - 2700.0) / 3600.0)


def test_sun_that_sets_before_a_full_disc():
    series = [row(i * STEP, el, 1.0) for i, el in enumerate([0.0, 0.8, 0.9, 0.8, 0.0, 0.0])]
    windows = [{"start_et_s": 2000.0, "end_et_s": 3.5 * STEP, "start_utc": "rise", "end_utc": "set",
                "start_truncated": False, "end_truncated": False}]
    fr = power.summarise(series, windows)["first_sunrise"]
    assert fr["set_before_full_disc"] and fr["to_full_disc_h"] is None
    assert 0 < fr["peak_disc_percent"] < 99


def test_sun_already_up_at_the_start_is_not_a_sunrise():
    series = [row(i * STEP, 2.0, 0.0) for i in range(4)]
    windows = [{"start_et_s": 0.0, "end_et_s": 3 * STEP, "start_utc": "a", "end_utc": "b",
                "start_truncated": True, "end_truncated": True}]
    out = power.summarise(series, windows)
    assert out["first_sunrise"] is None
    assert out["mean_vertical_w_m2"] == pytest.approx(1361.0 * math.cos(math.radians(2.0)))
    assert out["energy_vertical_kwh_m2"] == pytest.approx(out["mean_vertical_w_m2"] * 1.5 / 1000.0)
    assert out["partial_sun_percent"] == 0.0


def test_mean_power_matches_disc_percent_when_the_sun_is_low():
    """Near the horizontal plane at 1 AU the vertical-panel mean is 1361 x the disc average."""
    from lunar_core.check import sun_disc_percent
    series, windows = slow_sunrise()
    out = power.summarise(series, windows)
    assert out["mean_vertical_w_m2"] == pytest.approx(13.61 * sun_disc_percent(series), rel=1e-3)


def test_missing_distance_gives_no_power():
    assert power.summarise([{"et_s": 0, "sun_elevation_deg": 1, "sun_horizon_deg": 0},
                            {"et_s": 1, "sun_elevation_deg": 1, "sun_horizon_deg": 0}], []) is None


def test_leader_by_mean_power_and_rows_without_power():
    def r(key, w):
        return {"site": {"site_id": key, "origin": "reference"},
                "period": {"sunlit_percent": 50, "sun_disc_percent": 40, "earth_percent": 0, "both_percent": 0,
                           "longest_darkness_h": 1, "power": None if w is None else {"mean_vertical_w_m2": w}},
                "sun_next": {"up": False, "in_h": 1}, "earth_next": {"up": False, "in_h": 1},
                "now": {"sun": {"up": False, "elevation_deg": 0}}}
    assert compare.leaders([r("a", 500.0), r("b", 700.0), r("c", None)])["most_power"] == ["b"]
