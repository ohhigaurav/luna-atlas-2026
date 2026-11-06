"""A point the user clicked on the Moon, analysed like a catalogue site.

The app asks "when can I land *here*?" for any point, not only catalogue sites. A custom point
gets the fixed ID ``custom-point``. DEM assets are chosen by site ID, and this ID matches no
site-specific tile, so terrain comes from the regional 240 m map only (south of 60 S where it
exists); elsewhere the callers fall back to a flat horizon and say so.

Coordinates are rounded to 1e-6 deg (about 3 cm) so that equal clicks share a cache entry.
"""
from __future__ import annotations

from typing import Any

CUSTOM_SITE_ID = "custom-point"
COORD_DECIMALS = 6
CUSTOM_CAVEAT = ("A point you picked, not a catalogue site: terrain from the 240 m regional map only. "
                 "Measured against the 5 m site maps (Sites 001 and 004, Jan 2027), it is usually within a "
                 "few points of sunlight, but about 1 point in 7 differs by more than 10 points, and at the "
                 "published Site 001 and 004 points by 31 and 65 points. Use a nearby 5 m site result where "
                 "one exists.")


def normalise(latitude_deg: float, longitude_deg: float) -> tuple[float, float]:
    """Planetocentric latitude and east longitude in [0, 360), rounded."""
    lat = round(float(latitude_deg), COORD_DECIMALS)
    lon = round(float(longitude_deg) % 360.0, COORD_DECIMALS)
    if lon >= 360.0:
        lon = 0.0
    return lat, lon


def label(latitude_deg: float, longitude_deg: float) -> str:
    ns = "S" if latitude_deg < 0 else "N"
    return f"Point {abs(latitude_deg):.3f}° {ns}, {longitude_deg:.3f}° E"


def custom_site(latitude_deg: float, longitude_deg: float) -> dict[str, Any]:
    lat, lon = normalise(latitude_deg, longitude_deg)
    return {
        "site_id": CUSTOM_SITE_ID,
        "name": label(lat, lon),
        "latitude_deg": lat,
        "longitude_deg": lon,
        "latitude_type": "planetocentric",
        "longitude_direction": "east_positive",
        "source_url": None,
        "source_record": "User-selected point; not from a catalogue.",
        "terrain_status": "regional_only",
        "origin": "custom",
        "catalogue_kind": "user_point",
    }


def resolve(site_id: str | None, latitude_deg: float | None, longitude_deg: float | None,
            catalogue: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The site record for a request that names either a catalogue site or a point."""
    if site_id is not None:
        if site_id == CUSTOM_SITE_ID or site_id not in catalogue:
            raise ValueError(f"unknown site ID: {site_id}")
        return catalogue[site_id]
    if latitude_deg is None or longitude_deg is None:
        raise ValueError("give site_id, or latitude_deg and longitude_deg")
    return custom_site(latitude_deg, longitude_deg)
