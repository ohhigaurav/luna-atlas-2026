"""Moon-centred Sun and Earth directions for drawing the 3D scene.

The 3D globe needs, at every time on the dock, where the Sun and the Earth are as seen from the
Moon's centre, in the same body-fixed frame the analysis uses. This module returns exactly that
and nothing more: it makes no visibility claim and uses no terrain.

Conventions (also echoed in every response):

* Vectors are apparent positions from the Moon's centre (SPICE ``spkpos``, observer ``MOON``,
  the run's aberration correction) in the run's frame (MOON_ME). +X points to latitude 0,
  longitude 0; +Z to the north pole; +Y to 90 E. Unit vectors are dimensionless; distances in km.
* Sub-point latitude/longitude are planetocentric, longitude east-positive in [0, 360). On the
  spherical Moon the analysis requires (equal PCK radii) this is also the point where the body
  is directly overhead.
* Earth phase angle is SPICE ``phaseq`` (angle Sun-Earth-Moon at Earth, observer MOON). The
  illuminated fraction of Earth's disc seen from the Moon is (1 + cos(phase)) / 2.
* Angular radii use the equatorial radii below; they size the drawn discs only.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from lunar_core.spice_runtime import SPICE_LOCK

SUN_RADIUS_KM = 695_700.0
EARTH_RADIUS_KM = 6_378.1366
# 1e-7 in a unit vector is about 0.02 arcsec, far below anything the scene can draw.
UNIT_DECIMALS = 7
DEG_DECIMALS = 6
KM_DECIMALS = 3

CONVENTIONS = {
    "vector_origin": "Moon centre (SPICE observer MOON)",
    "axes": "+X toward latitude 0, longitude 0; +Z toward the north pole; +Y toward 90 E",
    "sub_point": "planetocentric latitude; longitude east-positive in [0, 360)",
    "earth_phase_angle": "SPICE phaseq: angle Sun-Earth-Moon at Earth",
    "earth_illuminated_fraction": "(1 + cos(phase_angle)) / 2, as seen from the Moon",
    "angular_radius": f"asin(R / distance) with R_sun={SUN_RADIUS_KM} km, R_earth={EARTH_RADIUS_KM} km",
    "interpolation": (
        "The subsolar point moves about 0.51 deg/h; linear interpolation of unit vectors at a 30 min step "
        "is within 0.01 deg of the sampled direction"
    ),
}


@dataclass(frozen=True, slots=True)
class BodyTrack:
    unit: list[list[float]]
    distance_km: list[float]
    sub_lat_deg: list[float]
    sub_lon_east_deg: list[float]
    angular_radius_deg: list[float]

    def as_payload(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "distance_km": self.distance_km,
            "sub_lat_deg": self.sub_lat_deg,
            "sub_lon_east_deg": self.sub_lon_east_deg,
            "angular_radius_deg": self.angular_radius_deg,
        }


def sub_point(vector_km: Sequence[float]) -> tuple[list[float], float, float, float]:
    """Unit vector, distance, planetocentric latitude and east longitude [0, 360)."""
    x, y, z = (float(vector_km[0]), float(vector_km[1]), float(vector_km[2]))
    distance = math.sqrt(x * x + y * y + z * z)
    if not math.isfinite(distance) or distance <= 0.0:
        raise ValueError("SPICE returned a zero or non-finite position vector")
    unit = [x / distance, y / distance, z / distance]
    latitude = math.degrees(math.asin(max(-1.0, min(1.0, unit[2]))))
    longitude = math.degrees(math.atan2(unit[1], unit[0])) % 360.0
    # -0.0 % 360 is 0.0, but 359.99999999999997 can round to 360.0 below; fold it back.
    if round(longitude, DEG_DECIMALS) >= 360.0:
        longitude = 0.0
    return unit, distance, latitude, longitude


def _angular_radius_deg(radius_km: float, distance_km: float) -> float:
    return math.degrees(math.asin(min(1.0, radius_km / distance_km)))


def _track(spice: Any, target: str, ets: Sequence[float], frame: str, abcorr: str, radius_km: float) -> BodyTrack:
    unit: list[list[float]] = []
    distance: list[float] = []
    lat: list[float] = []
    lon: list[float] = []
    radius: list[float] = []
    for et in ets:
        position_km, _light_time_s = spice.spkpos(target, et, frame, abcorr, "MOON")
        u, d, la, lo = sub_point(position_km)
        unit.append([round(component, UNIT_DECIMALS) for component in u])
        distance.append(round(d, KM_DECIMALS))
        lat.append(round(la, DEG_DECIMALS))
        lon.append(round(lo, DEG_DECIMALS))
        radius.append(round(_angular_radius_deg(radius_km, d), DEG_DECIMALS))
    return BodyTrack(unit, distance, lat, lon, radius)


def compute_sky_geometry(
    spice: Any,
    ets: Sequence[float],
    *,
    frame: str,
    aberration_correction: str,
    et_to_utc: Callable[[float], str],
) -> dict[str, Any]:
    """Columnar Sun/Earth tracks for the given ephemeris times, under the SPICE lock."""
    if not ets:
        raise ValueError("at least one epoch is required")
    with SPICE_LOCK:
        sun = _track(spice, "SUN", ets, frame, aberration_correction, SUN_RADIUS_KM)
        earth = _track(spice, "EARTH", ets, frame, aberration_correction, EARTH_RADIUS_KM)
        phase_deg: list[float] = []
        fraction: list[float] = []
        for et in ets:
            phase = float(spice.phaseq(et, "EARTH", "SUN", "MOON", aberration_correction))
            if not math.isfinite(phase):
                raise ValueError("SPICE phaseq returned a non-finite phase angle")
            phase_deg.append(round(math.degrees(phase), DEG_DECIMALS))
            fraction.append(round((1.0 + math.cos(phase)) / 2.0, DEG_DECIMALS))
        utc = [et_to_utc(et) for et in ets]
    return {
        "utc": utc,
        "et_s": [round(float(et), 3) for et in ets],
        "sun": sun.as_payload(),
        "earth": {
            **earth.as_payload(),
            "phase_angle_deg": phase_deg,
            "illuminated_fraction": fraction,
        },
    }
