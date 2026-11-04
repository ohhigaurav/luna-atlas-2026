"""Offline tests for the shadow-match geometry (synthetic DEMs, no rasters or kernels)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from tools import shadow_match as sm
from tools.compare_wac_illumination import stereographic_south


def test_frame_time() -> None:
    assert sm.frame_time("WAC_MOVIE_S20090920T0850").isoformat() == "2009-09-20T08:50:00+00:00"
    with pytest.raises(ValueError):
        sm.frame_time("nope")


@pytest.mark.parametrize(("lat", "lon"), [(-89.45, 222.69), (-89.9, 10.0), (-88.0, 300.0)])
def test_stereo_round_trip_matches_reference_projection(lat: float, lon: float) -> None:
    x, y = stereographic_south(lat, lon)
    p = sm.from_stereo(np.array([x]), np.array([y]), np.array([1234.0]))
    assert np.linalg.norm(p[0]) == pytest.approx(sm.R_MOON + 1234.0)
    bx, by = sm.to_stereo(p)
    assert bx[0] == pytest.approx(x, abs=1e-6) and by[0] == pytest.approx(y, abs=1e-6)


def test_grid_bilinear_and_outside_is_nan() -> None:
    g = sm.Grid(np.array([[0.0, 10.0], [20.0, 30.0]]), x0=0.0, y0=200.0, px=100.0)  # centres at x 50/150, y 150/50
    assert g.sample(np.array([100.0]), np.array([100.0]))[0] == pytest.approx(15.0)
    assert g.sample(np.array([50.0]), np.array([150.0]))[0] == pytest.approx(0.0)
    assert np.isnan(g.sample(np.array([500.0]), np.array([100.0]))[0])


def _sun_from_pole(elev_deg: float, toward_lon_deg: float) -> np.ndarray:
    """Unit vector seen from the south pole: elevation above the local horizontal, toward a meridian."""
    e, lon = math.radians(elev_deg), math.radians(toward_lon_deg)
    return np.array([math.cos(e) * math.cos(lon), math.cos(e) * math.sin(lon), -math.sin(e)])


def test_flat_ground_is_lit_and_sun_below_horizon_is_dark() -> None:
    dem = sm.Grid(np.zeros((400, 400)), x0=-40_000.0, y0=40_000.0, px=200.0)
    xs, ys = np.meshgrid(np.linspace(-2000, 2000, 5), np.linspace(-2000, 2000, 5))
    assert sm.lit_mask(dem, xs, ys, _sun_from_pole(1.0, 0.0), math.radians(0.267)).all()
    assert not sm.lit_mask(dem, xs, ys, _sun_from_pole(-2.0, 0.0), math.radians(0.267)).any()


def test_wall_casts_a_shadow_of_the_right_length_on_the_correct_side() -> None:
    # A 100 m high wall along y = +5 km (toward 0 E). Sun 1 deg up toward 0 E (i.e. +y): shadow on the
    # near (-y) side, length ~ 100 / tan(1 deg) ~ 5.7 km (ignoring curvature, which shortens it slightly).
    h = np.zeros((400, 400))
    rows_y = 40_000.0 - (np.arange(400) + 0.5) * 200.0
    h[np.abs(rows_y - 5_000.0) < 200.0, :] = 100.0
    dem = sm.Grid(h, x0=-40_000.0, y0=40_000.0, px=200.0)
    ys = np.arange(-6_000.0, 4_800.0, 100.0)
    xs = np.zeros_like(ys)
    lit = sm.lit_mask(dem, xs, ys, _sun_from_pole(1.0, 0.0), 0.0)
    dark_from = ys[~lit].min()
    assert 5_000.0 - dark_from == pytest.approx(5_700.0, abs=500.0)
    behind = sm.lit_mask(dem, np.zeros(3), np.array([6_000.0, 8_000.0, 10_000.0]), _sun_from_pole(1.0, 0.0), 0.0)
    assert behind.all()  # beyond the wall, toward the Sun: lit


def test_otsu_splits_bimodal_and_score_metrics() -> None:
    v = np.concatenate([np.full(500, 2), np.full(300, 150)])
    t = sm.otsu(v)
    assert 2 < t <= 150
    model = np.array([[True, True], [False, False]])
    photo = np.array([[True, False], [False, False]])
    s = sm.score(model, photo, np.ones_like(model))
    assert s["agreement"] == 0.75 and s["shadow_iou"] == pytest.approx(2 / 3) and s["model_lit_photo_dark"] == 0.25


def test_edge_band_marks_both_sides_of_a_boundary() -> None:
    m = np.zeros((10, 10), bool)
    m[:, 5:] = True
    band = sm.edge_band(m, 1)
    assert band[:, 3:7].all() and not band[:, 0:2].any() and not band[:, 8:].any()
