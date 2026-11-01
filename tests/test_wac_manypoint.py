"""Offline tests for tools/wac_manypoint.py helpers (no DEMs, kernels or maps)."""
from __future__ import annotations

import math

import numpy as np
import pytest
from lunar_core.horizon import HorizonBin, TerrainHorizon, interpolate_horizon

from tools import wac_manypoint as tool
from tools.check_sky_geometry import local_az_el
from tools.compare_wac_illumination import stereographic_south


@pytest.mark.parametrize(("lat", "lon"), [(-89.45, 222.69), (-89.78, 204.27), (-88.0, 0.0), (-89.999, 359.9)])
def test_inverse_stereographic_round_trip(lat: float, lon: float) -> None:
    back_lat, back_lon = tool.inverse_stereographic_south(*stereographic_south(lat, lon))
    assert back_lat == pytest.approx(lat, abs=1e-9)
    assert (back_lon - lon + 180.0) % 360.0 - 180.0 == pytest.approx(0.0, abs=1e-7)


def test_subpixel_offsets() -> None:
    assert tool.subpixel_offsets(1) == [0.0]
    assert tool.subpixel_offsets(3) == pytest.approx([-100 / 3, 0.0, 100 / 3])
    with pytest.raises(ValueError):
        tool.subpixel_offsets(0)


def test_strata_cover_full_range() -> None:
    assert tool.stratum_of(0.0) == 0 and tool.stratum_of(4.99) == 0 and tool.stratum_of(5.0) == 1
    assert tool.stratum_of(71.6) == 4 and tool.stratum_of(100.0) == 4 and tool.stratum_of(-1.0) is None


def test_selection_is_deterministic_stratified_and_order_independent() -> None:
    candidates = [(r, c, float((r * 7 + c * 3) % 70)) for r in range(30) for c in range(30)]
    a = tool.select_pixels(candidates, 4)
    b = tool.select_pixels(list(reversed(candidates)), 4)
    assert a == b
    assert [sum(1 for x in a if x[3] == k) for k in range(5)] == [4, 4, 4, 4, 4]
    assert all(tool.stratum_of(v) == k for _r, _c, v, k in a)
    assert len(tool.select_pixels(candidates[:3], 10)) <= 3


def _horizon(profile: list[float]) -> TerrainHorizon:
    step = 360.0 / len(profile)
    bins = tuple(HorizonBin(i * step, profile[i], 100.0, "complete", 10, 0) for i in range(len(profile)))
    return TerrainHorizon(1_737_400.0, 1_737_400.0, 0.0, 200_000.0, bins)


def test_lit_fractions_match_scalar_reference_path() -> None:
    rng = np.random.default_rng(1)
    profile = list(np.radians(rng.uniform(-0.5, 1.5, 720)))
    horizon = _horizon(profile)
    n = 2000
    angle = np.linspace(0, 4 * math.pi, n)
    tilt = np.radians(1.5) * np.sin(angle / 13.0)
    unit = np.stack([np.cos(angle) * np.cos(tilt), np.sin(angle) * np.cos(tilt), np.sin(tilt)], axis=1)
    dist = np.full(n, 1.496e8)
    lat, lon, radius = -89.45, 222.69, 1_737_400.0 + 1234.0
    limb, centre = tool.lit_fractions(unit, dist, lat, lon, radius, [b.azimuth_deg for b in horizon.bins], profile)
    ref_limb = ref_centre = 0
    for k in range(n):
        az, el, rng_km = local_az_el(list(unit[k] * dist[k]), lat, lon, radius / 1000.0)
        h = interpolate_horizon(horizon, az).elevation_rad
        sd = math.asin(tool.SUN_RADIUS_M / (rng_km * 1000.0))
        ref_limb += math.radians(el) + sd - h > 0
        ref_centre += math.radians(el) - h > 0
    assert limb == pytest.approx(ref_limb / n, abs=1.0 / n)
    assert centre == pytest.approx(ref_centre / n, abs=1.0 / n)
    assert 0.0 < centre < limb < 1.0


def test_spearman() -> None:
    assert tool.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert tool.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert tool.spearman([1, 2, 2, 3], [1, 2, 2, 3]) == pytest.approx(1.0)
    assert math.isnan(tool.spearman([1, 1, 1], [1, 2, 3]))


def _pixels(diffs: list[float]) -> list[dict[str, float]]:
    return [{"wac_pct": 2.0 * i, "model_limb_pct": 2.0 * i + d} for i, d in enumerate(diffs)]


def test_score_verdicts() -> None:
    assert tool.score(_pixels([1.0] * 40))["verdict"] == "PASS"
    assert tool.score(_pixels([1.0] * 10))["verdict"] == "INSUFFICIENT"
    assert tool.score(_pixels([8.0] * 40))["checks"]["median_diff_pp"]["pass"] is False
    spread = tool.score(_pixels([20.0, -20.0] * 20))
    assert spread["checks"]["share_within_10pp"]["pass"] is False and spread["verdict"] == "FAIL"
    assert tool.score([])["verdict"] == "INSUFFICIENT"
