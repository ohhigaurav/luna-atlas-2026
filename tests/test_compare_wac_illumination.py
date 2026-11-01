"""Pure parts of the WAC illumination comparison (no rasterio or SPICE needed)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import compare_wac_illumination as wac  # noqa: E402
from review_dem import stereographic_south as review_projection  # noqa: E402

# WKT exactly as GDAL's PDS driver reported it for WAC_POLE_ILL_PCT_SOUTH_100M.IMG (2026-11-01).
REAL_WKT = (
    'PROJCS["POLAR_STEREOGRAPHIC MOON",GEOGCS["GCS_MOON",DATUM["D_MOON",SPHEROID["MOON_polarRadius",1737400,0]],'
    'PRIMEM["Reference_Meridian",0],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]]],'
    'PROJECTION["Polar_Stereographic"],PARAMETER["latitude_of_origin",-90],PARAMETER["central_meridian",0],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],UNIT["unknown",1],AXIS["Easting",NORTH],AXIS["Northing",NORTH]]'
)


def test_projection_matches_the_reviewed_dem_projection() -> None:
    for lat, lon in [(-89.45, 222.69), (-88.0, 0.0), (-89.9, 129.4)]:
        x, y = wac.stereographic_south(lat, lon)
        rx, ry = review_projection(lat, lon, 1_737_400.0)
        assert x == pytest.approx(float(rx), abs=1e-6) and y == pytest.approx(float(ry), abs=1e-6)


def test_map_edge_is_88_south() -> None:
    # The map spans +/-60.7 km; 88 S must land just inside that.
    x, y = wac.stereographic_south(-88.0, 0.0)
    assert 60_000 < y < 60_700 and abs(x) < 1e-6


def test_real_wkt_is_accepted_and_wrong_ones_rejected() -> None:
    wac.check_crs(REAL_WKT)
    with pytest.raises(ValueError, match="radius"):
        wac.check_crs(REAL_WKT.replace("1737400", "1738100"))
    with pytest.raises(ValueError, match="latitude_of_origin"):
        wac.check_crs(REAL_WKT.replace('"latitude_of_origin",-90', '"latitude_of_origin",90'))


def test_pixel_lookup_uses_corner_transform_and_3x3_window() -> None:
    # 1214 x 1214 grid, 100 m pixels, upper-left corner at (-60700, 60700), like the real map.
    n = 1214
    array = np.zeros((n, n), dtype=np.float32)
    mask = np.zeros((n, n), dtype=bool)

    def inverse(x: float, y: float) -> tuple[float, float]:
        return (x + 60_700.0) / 100.0, (60_700.0 - y) / 100.0

    lat, lon = -89.45, 222.69
    x, y = wac.stereographic_south(lat, lon)
    col, row = int((x + 60_700) // 100), int((60_700 - y) // 100)
    array[row - 1:row + 2, col - 1:col + 2] = 20.0
    array[row, col] = 30.0
    array[row - 1, col - 1] = -1e-5  # float noise below zero is clamped
    stats = wac.pixel_stats(array, mask, inverse, lat, lon)
    assert stats["inside"] and (stats["row"], stats["col"]) == (row, col)
    assert stats["wac_centre_pct"] == 30.0
    assert stats["wac_3x3_min_pct"] == 0.0 and stats["wac_3x3_max_pct"] == 30.0
    mask[row, col] = True
    assert wac.pixel_stats(array, mask, inverse, lat, lon)["wac_centre_pct"] is None
    assert wac.pixel_stats(array, mask, inverse, -80.0, 0.0)["inside"] is False


def test_chunks_cover_period_exactly_within_api_limit() -> None:
    parts = wac.chunks(wac.WAC_START, wac.WAC_END)
    assert parts[0][0] == wac.WAC_START and parts[-1][1] == wac.WAC_END
    assert all(a[1] == b[0] for a, b in zip(parts, parts[1:], strict=False))
    assert all((b - a).days <= 59 for a, b in parts)


def test_series_fractions_distinguish_limb_and_centre() -> None:
    series = [
        {"sun_visible_upper_limb": True, "sun_elevation_deg": 1.0, "sun_horizon_deg": 0.5},
        {"sun_visible_upper_limb": True, "sun_elevation_deg": 0.3, "sun_horizon_deg": 0.5},  # limb only
        {"sun_visible_upper_limb": False, "sun_elevation_deg": -1.0, "sun_horizon_deg": 0.5},
        {"sun_visible_upper_limb": False, "sun_elevation_deg": -1.0, "sun_horizon_deg": 0.5},
    ]
    assert wac.series_fractions(series) == (0.5, 0.25, 4)


def test_chunks_are_weighted_by_duration_and_batched_by_four() -> None:
    calls: list[list[str]] = []

    def fake_run(**kw):
        calls.append(kw["site_ids"])
        first = kw["start_utc"].startswith("2010-02-15")
        lit = first  # first chunk fully lit, the rest dark
        return {"run_id": "r", "sites": [
            {"site": {"site_id": s}, "metrics": {"sunlit_percent": 100.0 if lit else 0.0},
             "series": [{"sun_visible_upper_limb": lit, "sun_elevation_deg": 1.0 if lit else -1.0,
                         "sun_horizon_deg": 0.0}] * 3}
            for s in kw["site_ids"]]}

    sites = [f"s{i}" for i in range(6)]
    out, run_ids = wac.modelled(sites, "terrain", fake_run)
    total = (wac.WAC_END - wac.WAC_START).total_seconds()
    expected = 100 * 59 * 86400 / total
    assert out["s5"]["model_limb_pct"] == pytest.approx(expected)
    assert out["s0"]["model_windows_sunlit_pct"] == pytest.approx(expected)
    assert max(len(c) for c in calls) == 4 and len(run_ids) == len(calls)


@pytest.mark.parametrize(("row", "expected"), [
    ({"inside": True, "wac_centre_pct": 50.0, "wac_3x3_min_pct": 45.0, "wac_3x3_max_pct": 52.0, "model_limb_pct": 58.0}, "PASS"),
    ({"inside": True, "wac_centre_pct": 50.0, "wac_3x3_min_pct": 45.0, "wac_3x3_max_pct": 52.0, "model_limb_pct": 61.0}, "FAIL"),
    ({"inside": True, "wac_centre_pct": 50.0, "wac_3x3_min_pct": 30.0, "wac_3x3_max_pct": 52.0, "model_limb_pct": 90.0}, "UNSCORED"),
    ({"inside": False}, "OUTSIDE/NODATA"),
])
def test_verdict_follows_the_predeclared_criterion(row, expected) -> None:
    assert wac.verdict(row) == expected
