#!/usr/bin/env python3
"""Check /api/sky-geometry on the real kernels before the 3D scene relies on it.

Two kinds of check, with pass limits fixed here before the first run:

A. Cross-check against the analysis path. For two sites (Malapert, south pole; Apollo 11,
   near the equator) the tool runs a flat analysis at 0 m and rebuilds each sample's local Sun
   and Earth azimuth/elevation from the sky-geometry vectors (topocentric = target - site). The
   two paths use different SPICE routines (spkpos from the Moon's centre vs azlcpo from the
   surface point), so agreement checks frame, axes, longitude sign and the et grid together.
   Pass: |d elevation| and |d azimuth x cos(elevation)| <= 0.01 deg for every sample, Sun and
   Earth; |d range| <= 1 km (Earth) and <= 50 km (Sun; the unit vector is rounded to 1e-7).

B. Physical limits over 2027 at a 6 h step.
   * |subsolar latitude| <= 1.6 deg (lunar equator ~1.54 deg from the ecliptic)
   * |sub-Earth latitude| <= 7.0 deg and sub-Earth longitude within 9 deg of 0 (libration)
   * Sun distance 1.45e8-1.53e8 km; Earth distance 3.50e5-4.10e5 km
   * mean subsolar longitude rate = -360/29.5306 deg/day within 2% (the Sun moves west)
   * Earth lit fraction from phaseq agrees with (1 - cos(angle Sun-Moon-Earth)) / 2 within 0.005

Passing says the endpoint is self-consistent and agrees with the analysis code. Absolute accuracy
of that code against JPL Horizons is Gate B (tools/horizons_golden.py), recorded separately.

Usage:  python tools/check_sky_geometry.py
"""
from __future__ import annotations

import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

CROSS_SITES = ("reference-malapert-massif", "reference-apollo-11")
CROSS_WINDOW = ("2027-01-01T00:00:00Z", "2027-01-04T00:00:00Z")
CROSS_STEP_MIN = 30
ANGLE_TOL_DEG = 0.01
RANGE_TOL_KM = {"sun": 50.0, "earth": 1.0}
YEAR_WINDOW = ("2027-01-01T00:00:00Z", "2027-12-31T00:00:00Z")
YEAR_STEP_MIN = 360
SYNODIC_DAYS = 29.530589


def local_az_el(target_km: list[float], lat_deg: float, lon_deg: float, radius_km: float) -> tuple[float, float, float]:
    """Azimuth (clockwise from north), elevation (deg) and range (km) of a Moon-centred vector."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    site = [radius_km * math.cos(lat) * math.cos(lon), radius_km * math.cos(lat) * math.sin(lon), radius_km * math.sin(lat)]
    rel = [target_km[i] - site[i] for i in range(3)]
    rng = math.sqrt(sum(c * c for c in rel))
    up = [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
    east = [-math.sin(lon), math.cos(lon), 0.0]
    north = [-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)]

    def dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    elevation = math.degrees(math.asin(max(-1.0, min(1.0, dot(rel, up) / rng))))
    azimuth = math.degrees(math.atan2(dot(rel, east), dot(rel, north))) % 360.0
    return azimuth, elevation, rng


def azimuth_diff_deg(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def cross_check(sky: dict[str, Any], run: dict[str, Any], radius_km: float) -> dict[str, Any]:
    series = sky["series"]
    out: dict[str, Any] = {}
    for result in run["sites"]:
        # Analysis payload shape: {"site": {site_id, latitude_deg, longitude_deg, ...}, "series": [...]}.
        site, timeline = result["site"], result["series"]
        if len(timeline) != len(series["et_s"]):
            raise SystemExit(f"grid mismatch for {site['site_id']}: {len(timeline)} vs {len(series['et_s'])}")
        worst = {f"{body}_{k}": 0.0 for body in ("sun", "earth") for k in ("elevation_deg", "azimuth_cos_el_deg", "range_km")}
        for index, row in enumerate(timeline):
            if abs(float(row["et_s"]) - float(series["et_s"][index])) > 1e-3:
                raise SystemExit(f"epoch mismatch at sample {index}")
            for body in ("sun", "earth"):
                track = series[body]
                vector = [c * track["distance_km"][index] for c in track["unit"][index]]
                az, el, rng = local_az_el(vector, site["latitude_deg"], site["longitude_deg"], radius_km)
                d_el = abs(el - row[f"{body}_elevation_deg"])
                d_az = abs(azimuth_diff_deg(az, row[f"{body}_azimuth_deg"])) * math.cos(math.radians(el))
                d_rng = abs(rng - row[f"{body}_range_m"] / 1000.0)
                worst[f"{body}_elevation_deg"] = max(worst[f"{body}_elevation_deg"], d_el)
                worst[f"{body}_azimuth_cos_el_deg"] = max(worst[f"{body}_azimuth_cos_el_deg"], d_az)
                worst[f"{body}_range_km"] = max(worst[f"{body}_range_km"], d_rng)
        passed = all(
            worst[f"{b}_elevation_deg"] <= ANGLE_TOL_DEG
            and worst[f"{b}_azimuth_cos_el_deg"] <= ANGLE_TOL_DEG
            and worst[f"{b}_range_km"] <= RANGE_TOL_KM[b]
            for b in ("sun", "earth")
        )
        out[site["site_id"]] = {"samples": len(timeline), "max_abs_diff": worst, "pass": passed}
    return out


def physical_limits(sky: dict[str, Any]) -> dict[str, Any]:
    s = sky["series"]
    sun, earth = s["sun"], s["earth"]
    checks: dict[str, Any] = {}

    def record(name: str, value: float, ok: bool, limit: str) -> None:
        checks[name] = {"value": round(value, 6), "limit": limit, "pass": ok}

    m = max(abs(v) for v in sun["sub_lat_deg"])
    record("max_abs_subsolar_lat_deg", m, m <= 1.6, "<= 1.6")
    m = max(abs(v) for v in earth["sub_lat_deg"])
    record("max_abs_sub_earth_lat_deg", m, m <= 7.0, "<= 7.0")
    m = max(abs(azimuth_diff_deg(v, 0.0)) for v in earth["sub_lon_east_deg"])
    record("max_abs_sub_earth_lon_deg", m, m <= 9.0, "<= 9.0")
    lo, hi = min(sun["distance_km"]), max(sun["distance_km"])
    record("sun_distance_min_km", lo, lo >= 1.45e8, ">= 1.45e8")
    record("sun_distance_max_km", hi, hi <= 1.53e8, "<= 1.53e8")
    lo, hi = min(earth["distance_km"]), max(earth["distance_km"])
    record("earth_distance_min_km", lo, lo >= 3.50e5, ">= 3.50e5")
    record("earth_distance_max_km", hi, hi <= 4.10e5, "<= 4.10e5")
    # Unwrap the subsolar longitude and fit the mean rate end to end.
    total = sum(azimuth_diff_deg(b, a) for a, b in zip(sun["sub_lon_east_deg"], sun["sub_lon_east_deg"][1:], strict=False))
    days = (s["et_s"][-1] - s["et_s"][0]) / 86_400.0
    rate, expected = total / days, -360.0 / SYNODIC_DAYS
    record("subsolar_lon_rate_deg_per_day", rate, abs(rate - expected) <= 0.02 * abs(expected), f"{expected:.4f} +/- 2%")
    worst = 0.0
    for u_sun, u_earth, frac in zip(sun["unit"], earth["unit"], earth["illuminated_fraction"], strict=True):
        cos_angle = sum(a * b for a, b in zip(u_sun, u_earth, strict=True))
        worst = max(worst, abs(frac - (1.0 - cos_angle) / 2.0))
    record("max_abs_fraction_vs_vectors", worst, worst <= 0.005, "<= 0.005")
    return checks


def main() -> int:
    from lunar_core.analysis_service import run_analysis, run_sky_geometry
    from lunar_core.api_models import AnalysisRequest, SkyGeometryRequest

    sky_cross = run_sky_geometry(SkyGeometryRequest(start_utc=CROSS_WINDOW[0], end_utc=CROSS_WINDOW[1], step_min=CROSS_STEP_MIN))
    run = run_analysis(AnalysisRequest(
        site_ids=list(CROSS_SITES), start_utc=CROSS_WINDOW[0], end_utc=CROSS_WINDOW[1],
        coarse_step_min=CROSS_STEP_MIN, horizon_mode="flat", sun_observer_height_m=0.0, antenna_height_m=0.0,
    ))
    radius_km = float(sky_cross["moon_reference_radius_m"]) / 1000.0
    cross = cross_check(sky_cross, run, radius_km)
    sky_year = run_sky_geometry(SkyGeometryRequest(start_utc=YEAR_WINDOW[0], end_utc=YEAR_WINDOW[1], step_min=YEAR_STEP_MIN))
    limits = physical_limits(sky_year)
    passed = all(item["pass"] for item in cross.values()) and all(item["pass"] for item in limits.values())

    print(f"Sky geometry check — frame {sky_cross['frame']}, {sky_cross['aberration_correction']}, "
          f"kernel pool {sky_cross['provenance']['kernel_pool']}")
    print(f"\nA. Cross-check vs analysis run {run['run_id']} (limit {ANGLE_TOL_DEG} deg)")
    for site_id, item in cross.items():
        w = item["max_abs_diff"]
        print(f"  {site_id:28s} {'PASS' if item['pass'] else 'FAIL'}  n={item['samples']}  "
              f"sun el {w['sun_elevation_deg']:.2e} az {w['sun_azimuth_cos_el_deg']:.2e} rng {w['sun_range_km']:.2f} km | "
              f"earth el {w['earth_elevation_deg']:.2e} az {w['earth_azimuth_cos_el_deg']:.2e} rng {w['earth_range_km']:.3f} km")
    print(f"\nB. Physical limits, {YEAR_WINDOW[0][:10]} to {YEAR_WINDOW[1][:10]}, {sky_year['settings']['sample_count']} samples")
    for name, item in limits.items():
        print(f"  {name:32s} {'PASS' if item['pass'] else 'FAIL'}  {item['value']}  ({item['limit']})")
    print(f"\nOVERALL: {'PASS' if passed else 'FAIL'}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "data" / "derived" / f"sky_geometry_check_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "created_utc": stamp, "pass": passed, "analysis_run_id": run["run_id"],
        "limits": {"angle_deg": ANGLE_TOL_DEG, "range_km": RANGE_TOL_KM},
        "cross_check": cross, "physical_limits": limits,
        "provenance": sky_cross["provenance"],
    }, indent=2), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
