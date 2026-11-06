"""One-click "verify with NASA JPL" links (PRD: Horizons verify link).

Each link opens JPL Horizons' own answer, as plain text in the browser, for where the Sun or the
Earth is in the sky from the same lunar surface point at the same second. Next to it the app shows
our value from the same run. Both are positions in the sky above the local level horizon (no
terrain): Horizons has no lunar hills, so it checks our ephemeris and geometry, not our horizon
model. Gate B is this comparison done systematically (worst 0.04 arcsec,
validation/evidence/gate_b_geometry_2026-10-28.md).

Query settings match Gate B (tools/horizons_golden.py): observer ``coord@301`` (Moon, MOON_ME,
1737.4 km sphere, so geodetic = planetocentric), altitude above that sphere = ground elevation
from the DEM + observer height, quantities 4 (azimuth/elevation, azimuth clockwise from north) and
20 (range), airless apparent positions, UT time.
"""
from __future__ import annotations

import urllib.parse
from datetime import UTC, datetime
from typing import Any

HORIZONS_API = "https://ssd.jpl.nasa.gov/api/horizons.api"
TARGET_CODES = {"SUN": "10", "EARTH": "399"}
JD_UNIX_EPOCH = 2440587.5
NOTE = ("Opens NASA JPL Horizons' own answer for this point and second. It has no lunar terrain, so "
        "compare sky positions (azimuth, elevation above the level horizon), not sunrise times.")


def _jd_ut(utc: str) -> float:
    parsed = datetime.fromisoformat(utc.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"epoch must be explicit UTC: {utc}")
    return JD_UNIX_EPOCH + parsed.timestamp() / 86_400.0


def horizons_url(target: str, latitude_deg: float, longitude_deg: float, altitude_m: float, utc: str) -> str:
    if target not in TARGET_CODES:
        raise ValueError(f"unsupported target {target!r}")
    params = {
        "format": "text",
        "COMMAND": f"'{TARGET_CODES[target]}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@301'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{longitude_deg % 360.0:.6f},{latitude_deg:.6f},{altitude_m / 1000.0:.6f}'",
        "TLIST": f"'{_jd_ut(utc):.9f}'",
        "TLIST_TYPE": "'JD'",
        "TIME_TYPE": "'UT'",
        "QUANTITIES": "'4,20'",
        "ANG_FORMAT": "'DEG'",
        "APPARENT": "'AIRLESS'",
        "RANGE_UNITS": "'KM'",
        "EXTRA_PREC": "'YES'",
    }
    return HORIZONS_API + "?" + urllib.parse.urlencode(params)


def verify_block(site_result: dict[str, Any], row: dict[str, Any], *, sun_height_m: float,
                 antenna_height_m: float) -> dict[str, Any]:
    """Our Sun/Earth azimuth and elevation at one series row, with the matching Horizons links."""
    site = site_result["site"]
    lat, lon = float(site["latitude_deg"]), float(site["longitude_deg"])
    ground = float((site_result.get("terrain") or {}).get("site_ground_elevation_m") or 0.0)
    utc = str(row["utc"])
    out: dict[str, Any] = {"utc": utc, "note": NOTE}
    for key, target, height in (("sun", "SUN", sun_height_m), ("earth", "EARTH", antenna_height_m)):
        out[key] = {
            "ours_azimuth_deg": round(float(row[f"{key}_azimuth_deg"]), 4),
            "ours_elevation_deg": round(float(row[f"{key}_elevation_deg"]), 4),
            "observer_altitude_m": round(ground + height, 2),
            "horizons_url": horizons_url(target, lat, lon, ground + height, utc),
        }
    return out
