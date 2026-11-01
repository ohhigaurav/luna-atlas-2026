"""Offline tests for tools/check_sky_geometry.py helpers (no kernels)."""
from __future__ import annotations

import math

import pytest

from tools import check_sky_geometry as tool

R = 1737.4


def test_local_frame_up_east_north_at_equator() -> None:
    _az, el, rng = tool.local_az_el([R + 1000.0, 0.0, 0.0], 0.0, 0.0, R)
    assert el == pytest.approx(90.0) and rng == pytest.approx(1000.0)
    az, el, _ = tool.local_az_el([R, 1e6, 0.0], 0.0, 0.0, R)
    assert az == pytest.approx(90.0) and el == pytest.approx(0.0, abs=1e-6)
    az, _el, _ = tool.local_az_el([R, 0.0, 1e6], 0.0, 0.0, R)
    assert az == pytest.approx(0.0, abs=1e-9)


def test_local_frame_south_pole_north_points_to_site_longitude() -> None:
    # From near the south pole, a far target along the site's own meridian toward the equator is due north.
    lon = 40.0
    far = [1e6 * math.cos(math.radians(lon)), 1e6 * math.sin(math.radians(lon)), -R]
    az, el, _ = tool.local_az_el(far, -89.9, lon, R)
    assert tool.azimuth_diff_deg(az, 0.0) == pytest.approx(0.0, abs=1e-6)
    assert -1.0 < el < 1.0


def _series(days: int, step_h: float) -> dict:
    n = int(days * 24 / step_h) + 1
    ets = [i * step_h * 3600.0 for i in range(n)]
    sun_units, lons, earth_units, fracs = [], [], [], []
    for et in ets:
        angle = -2.0 * math.pi * et / (tool.SYNODIC_DAYS * 86400.0)
        u_sun = [math.cos(angle), math.sin(angle), 0.0]
        u_earth = [1.0, 0.0, 0.0]
        sun_units.append(u_sun)
        earth_units.append(u_earth)
        lons.append(math.degrees(angle) % 360.0)
        fracs.append((1.0 - u_sun[0]) / 2.0)
    return {"series": {
        "et_s": ets,
        "sun": {"unit": sun_units, "sub_lat_deg": [0.5] * n, "sub_lon_east_deg": lons, "distance_km": [1.496e8] * n},
        "earth": {"unit": earth_units, "sub_lat_deg": [-6.0] * n, "sub_lon_east_deg": [355.0] * n,
                  "distance_km": [3.8e5] * n, "illuminated_fraction": fracs},
    }}


def test_physical_limits_pass_on_ideal_series_and_catch_wrong_direction() -> None:
    good = tool.physical_limits(_series(365, 6.0))
    assert all(item["pass"] for item in good.values()), good
    bad = _series(365, 6.0)
    bad["series"]["sun"]["sub_lon_east_deg"] = [(-v) % 360.0 for v in bad["series"]["sun"]["sub_lon_east_deg"]]
    assert tool.physical_limits(bad)["subsolar_lon_rate_deg_per_day"]["pass"] is False


def test_cross_check_detects_a_flipped_longitude() -> None:
    sky = _series(1, 0.5)
    rows = []
    for i, et in enumerate(sky["series"]["et_s"]):
        row = {"et_s": et}
        for body in ("sun", "earth"):
            vec = [c * sky["series"][body]["distance_km"][i] for c in sky["series"][body]["unit"][i]]
            az, el, rng = tool.local_az_el(vec, -86.0, 357.0, R)
            row |= {f"{body}_azimuth_deg": az, f"{body}_elevation_deg": el, f"{body}_range_m": rng * 1000.0}
        rows.append(row)
    run = {"sites": [{"site_id": "s", "latitude_deg": -86.0, "longitude_deg": 357.0, "series": rows}]}
    assert tool.cross_check(sky, run, R)["s"]["pass"] is True
    run["sites"][0]["longitude_deg"] = 3.0  # west-positive mistake
    assert tool.cross_check(sky, run, R)["s"]["pass"] is False
