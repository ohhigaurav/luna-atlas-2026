"""Geometric visibility margins defined by PRD SR-05 and SR-06.

All angular inputs/outputs are radians and all distances/radii are metres. The caller is
responsible for supplying one consistent local horizon and a declared ephemeris/frame chain.
A positive margin means visible under that geometric definition; it does not imply power
availability or a viable radio-frequency link.
"""

from __future__ import annotations

from math import asin, isfinite


def angular_semidiameter_rad(body_radius_m: float, range_m: float) -> float:
    """Return ``asin(body_radius / range)`` for a spherical body's angular semidiameter."""
    if not isfinite(body_radius_m) or body_radius_m <= 0:
        raise ValueError("body_radius_m must be finite and positive")
    if not isfinite(range_m) or range_m <= body_radius_m:
        raise ValueError("range_m must be finite and greater than body_radius_m")
    return asin(body_radius_m / range_m)


def sun_upper_limb_margin_rad(
    *,
    sun_elevation_rad: float,
    sun_range_m: float,
    sun_radius_m: float,
    horizon_elevation_rad: float,
) -> float:
    """PRD SR-05: Sun upper-limb margin relative to the local terrain horizon."""
    if not isfinite(sun_elevation_rad) or not isfinite(horizon_elevation_rad):
        raise ValueError("Sun elevation and horizon elevation must be finite")
    sun_semidiameter = angular_semidiameter_rad(sun_radius_m, sun_range_m)
    return sun_elevation_rad + sun_semidiameter - horizon_elevation_rad


def earth_centre_clear_margin_rad(
    *,
    earth_elevation_rad: float,
    horizon_elevation_rad: float,
    min_clearance_rad: float = 0.0,
) -> float:
    """PRD SR-06: Earth-centre clearance margin (not a communications-availability metric)."""
    if not all(isfinite(value) for value in (
        earth_elevation_rad, horizon_elevation_rad, min_clearance_rad
    )):
        raise ValueError("Earth elevation, horizon elevation and clearance must be finite")
    if min_clearance_rad < 0:
        raise ValueError("min_clearance_rad must be non-negative")
    return earth_elevation_rad - horizon_elevation_rad - min_clearance_rad


def earth_disc_visible_margin_rad(
    *,
    earth_elevation_rad: float,
    earth_range_m: float,
    earth_radius_m: float,
    horizon_elevation_rad: float,
    min_clearance_rad: float = 0.0,
) -> float:
    """P1-style margin for any part of Earth's disc to clear the terrain horizon.

    This is separate from Earth-centre-clear and must be labelled separately in the API/UI.
    """
    if not isfinite(earth_elevation_rad) or not isfinite(horizon_elevation_rad):
        raise ValueError("Earth elevation and horizon elevation must be finite")
    if not isfinite(min_clearance_rad) or min_clearance_rad < 0:
        raise ValueError("min_clearance_rad must be finite and non-negative")
    semidiameter = angular_semidiameter_rad(earth_radius_m, earth_range_m)
    return earth_elevation_rad + semidiameter - horizon_elevation_rad - min_clearance_rad
