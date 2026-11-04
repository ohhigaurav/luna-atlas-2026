"""Terrain-horizon geometry with explicit coverage semantics.

Terrain elevations are metres relative to the reference radius supplied by the caller. The
formula follows PRD SR-04; the module does not inspect raster files or certify DEM provenance.
A horizon calculated from partial/NoData rays is returned for diagnostics but is marked
incomplete so the caller cannot silently treat it as terrain-verified.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import atan2, cos, isfinite, sin, sqrt
from typing import Literal

CoverageStatus = Literal["complete", "incomplete", "none"]


@dataclass(frozen=True, slots=True)
class TerrainSample:
    distance_m: float
    elevation_m: float | None


@dataclass(frozen=True, slots=True)
class HorizonBin:
    azimuth_deg: float
    elevation_rad: float | None
    controlling_distance_m: float | None
    coverage_status: CoverageStatus
    sample_count: int
    nodata_count: int


@dataclass(frozen=True, slots=True)
class TerrainHorizon:
    reference_radius_m: float
    observer_radius_m: float
    observer_height_m: float
    max_range_m: float
    bins: tuple[HorizonBin, ...]


@dataclass(frozen=True, slots=True)
class InterpolatedHorizon:
    azimuth_deg: float
    elevation_rad: float | None
    coverage_complete: bool
    contributing_azimuths_deg: tuple[float, ...]


def flat_horizon_elevation_rad(reference_radius_m: float, observer_height_m: float) -> float:
    """Analytical dip angle from a spherical surface, as defined in PRD SR-04."""
    if not isfinite(reference_radius_m) or reference_radius_m <= 0:
        raise ValueError("reference_radius_m must be finite and positive")
    if not isfinite(observer_height_m) or observer_height_m < 0:
        raise ValueError("observer_height_m must be finite and non-negative")
    # Equivalent to -acos(R / (R + h)), but better conditioned for very small h/R.
    return -atan2(sqrt(observer_height_m * (2.0 * reference_radius_m + observer_height_m)),
                  reference_radius_m)


def apparent_elevation_rad(
    *,
    reference_radius_m: float,
    observer_radius_m: float,
    distance_m: float,
    terrain_elevation_m: float,
) -> float:
    """Apparent terrain elevation at ground distance ``distance_m`` using PRD SR-04."""
    values = (reference_radius_m, observer_radius_m, distance_m, terrain_elevation_m)
    if any(not isfinite(value) for value in values):
        raise ValueError("terrain geometry inputs must be finite")
    if reference_radius_m <= 0 or observer_radius_m <= 0:
        raise ValueError("reference and observer radii must be positive")
    if distance_m < 0:
        raise ValueError("distance_m must be non-negative")
    terrain_radius_m = reference_radius_m + terrain_elevation_m
    if terrain_radius_m <= 0:
        raise ValueError("terrain elevation puts the sample at a non-positive radius")
    theta = distance_m / reference_radius_m
    numerator = terrain_radius_m * cos(theta) - observer_radius_m
    denominator = terrain_radius_m * sin(theta)
    return atan2(numerator, denominator)


def calculate_terrain_horizon(
    rays: Mapping[float, Sequence[TerrainSample]],
    *,
    reference_radius_m: float,
    site_ground_elevation_m: float = 0.0,
    observer_height_m: float = 2.0,
    max_range_m: float = 200_000.0,
) -> TerrainHorizon:
    """Calculate H(azimuth) from sampled terrain rays.

    ``rays`` maps azimuth degrees clockwise from local north to ordered radial samples. An
    elevation of ``None`` represents NoData. Any NoData sample makes that azimuth incomplete;
    the implementation never substitutes zero or a synthetic wall for missing terrain.
    The known-sample maximum is retained for debugging, but its status prevents treating it as a
    complete horizon.
    """
    for name, value in (
        ("reference_radius_m", reference_radius_m),
        ("site_ground_elevation_m", site_ground_elevation_m),
        ("observer_height_m", observer_height_m),
        ("max_range_m", max_range_m),
    ):
        if not isfinite(value):
            raise ValueError(f"{name} must be finite")
    if reference_radius_m <= 0:
        raise ValueError("reference_radius_m must be positive")
    if observer_height_m < 0:
        raise ValueError("observer_height_m must be non-negative")
    if max_range_m <= 0:
        raise ValueError("max_range_m must be positive")
    observer_radius_m = reference_radius_m + site_ground_elevation_m + observer_height_m
    if observer_radius_m <= 0:
        raise ValueError("observer radius must be positive")

    normalised: dict[float, Sequence[TerrainSample]] = {}
    for raw_azimuth, samples in rays.items():
        if not isfinite(raw_azimuth):
            raise ValueError("azimuth values must be finite")
        azimuth = raw_azimuth % 360.0
        key = 0.0 if abs(azimuth - 360.0) < 1e-10 else azimuth
        if any(abs(key - existing) < 1e-10 for existing in normalised):
            raise ValueError(f"duplicate azimuth bin after wrap normalisation: {raw_azimuth}")
        normalised[key] = samples

    bins: list[HorizonBin] = []
    for azimuth in sorted(normalised):
        samples = normalised[azimuth]
        previous_distance = -1.0
        elevations: list[tuple[float, float]] = []
        nodata_count = 0
        for sample in samples:
            if not isfinite(sample.distance_m) or sample.distance_m < 0:
                raise ValueError(f"distances for azimuth {azimuth} must be finite and non-negative")
            if sample.distance_m <= previous_distance:
                raise ValueError(f"distances for azimuth {azimuth} must be strictly increasing")
            if sample.distance_m > max_range_m:
                raise ValueError(f"sample exceeds max_range_m for azimuth {azimuth}")
            previous_distance = sample.distance_m
            if sample.elevation_m is None:
                nodata_count += 1
                continue
            if not isfinite(sample.elevation_m):
                raise ValueError(f"terrain elevation for azimuth {azimuth} must be finite or None")
            if sample.distance_m == 0.0:
                continue  # the ground under the observer is never a horizon candidate (0/0 at height 0)
            elevation = apparent_elevation_rad(
                reference_radius_m=reference_radius_m,
                observer_radius_m=observer_radius_m,
                distance_m=sample.distance_m,
                terrain_elevation_m=sample.elevation_m,
            )
            elevations.append((elevation, sample.distance_m))

        if not elevations:
            bins.append(HorizonBin(
                azimuth_deg=azimuth,
                elevation_rad=None,
                controlling_distance_m=None,
                coverage_status="none",
                sample_count=len(samples),
                nodata_count=nodata_count,
            ))
            continue
        horizon_elevation, controlling_distance = max(elevations, key=lambda item: item[0])
        # Coverage is complete only if the caller supplied the local origin and reached the
        # declared maximum range. Otherwise unseen terrain could still control the horizon.
        distance_epsilon_m = max(1e-6, max_range_m * 1e-9)
        covers_origin = bool(samples) and samples[0].distance_m <= distance_epsilon_m
        covers_range = bool(samples) and samples[-1].distance_m >= max_range_m - distance_epsilon_m
        is_complete = not nodata_count and covers_origin and covers_range
        bins.append(HorizonBin(
            azimuth_deg=azimuth,
            elevation_rad=horizon_elevation,
            controlling_distance_m=controlling_distance,
            coverage_status="complete" if is_complete else "incomplete",
            sample_count=len(samples),
            nodata_count=nodata_count,
        ))

    return TerrainHorizon(
        reference_radius_m=reference_radius_m,
        observer_radius_m=observer_radius_m,
        observer_height_m=observer_height_m,
        max_range_m=max_range_m,
        bins=tuple(bins),
    )


# Per-horizon lookup tables, built once instead of on every call (an analysis makes thousands of
# calls on the same horizon). Keyed by id() of the bins tuple; the tuple itself is stored and
# compared with ``is`` so a recycled id can never return another horizon's tables.
_TABLES: dict[int, tuple[tuple[HorizonBin, ...], tuple[float, ...], bool, tuple[float, ...] | None]] = {}
_TABLES_MAX = 16


def _tables(bins: tuple[HorizonBin, ...]) -> tuple[tuple[float, ...], bool, tuple[float, ...] | None]:
    """(sorted azimuths, ascending?, per-segment |slope| for uniform bins from 0 deg, else None)."""
    hit = _TABLES.get(id(bins))
    if hit is not None and hit[0] is bins:
        return hit[1], hit[2], hit[3]
    azimuths = tuple(item.azimuth_deg for item in bins)
    ascending = all(a < b for a, b in zip(azimuths, azimuths[1:], strict=False))
    n = len(bins)
    slopes: tuple[float, ...] | None = None
    if n >= 2:
        step = 360.0 / n
        if all(abs(item.azimuth_deg - index * step) <= 1e-6 for index, item in enumerate(bins)):
            values = [item.elevation_rad for item in bins]
            slopes = tuple(
                float("inf") if values[i] is None or values[(i + 1) % n] is None
                else abs(values[(i + 1) % n] - values[i]) / step  # type: ignore[operator]
                for i in range(n)
            )
    if len(_TABLES) >= _TABLES_MAX:
        _TABLES.clear()
    _TABLES[id(bins)] = (bins, azimuths, ascending, slopes)
    return azimuths, ascending, slopes


def horizon_slope_bound_rad_per_deg(
    horizon: TerrainHorizon, azimuth_a_deg: float, azimuth_b_deg: float
) -> float:
    """Upper bound on |dH/d(azimuth)| of the linear interpolant over the arc from a to b.

    The arc is the shorter one between the two azimuths, widened by one bin on each side so a
    target whose azimuth overshoots slightly inside the step is still covered. Missing bins give
    ``inf`` (no bound can be certified over unknown terrain).
    """
    if not (isfinite(azimuth_a_deg) and isfinite(azimuth_b_deg)):
        raise ValueError("azimuths must be finite")
    bins = horizon.bins
    n = len(bins)
    if n < 2:
        return float("inf")
    step = 360.0 / n
    _azimuths, _ascending, table = _tables(bins)
    if table is None:
        raise ValueError("slope bound requires uniformly spaced horizon bins starting at 0 deg")
    slopes = table

    delta = (azimuth_b_deg - azimuth_a_deg + 180.0) % 360.0 - 180.0
    start = (azimuth_a_deg if delta >= 0 else azimuth_b_deg) % 360.0
    span = abs(delta)
    if span + 2 * step >= 180.0:
        return max(slopes)
    first = int(start // step) - 1
    last = int((start + span) // step) + 1
    return max(slopes[k % n] for k in range(first, last + 1))


def interpolate_horizon(horizon: TerrainHorizon, azimuth_deg: float) -> InterpolatedHorizon:
    """Linearly interpolate H(a) with wrap-around at 0°/360° (PRD SR-04).

    The returned coverage flag is false if any contributing bin is incomplete or has no valid
    elevation. A numerical value may still be returned for diagnostic plots, but it is not a
    verified terrain horizon.
    """
    if not isfinite(azimuth_deg):
        raise ValueError("azimuth_deg must be finite")
    if not horizon.bins:
        return InterpolatedHorizon(azimuth_deg % 360.0, None, False, ())
    azimuth = azimuth_deg % 360.0
    bins = horizon.bins

    azimuths, ascending, _slopes = _tables(bins)
    exact: HorizonBin | None = None
    if ascending:
        # Same result as a linear scan: only the neighbours of the insertion point can lie within 1e-10.
        pos = bisect_left(azimuths, azimuth)
        for k in (pos - 1, pos, pos + 1):
            if 0 <= k < len(bins) and abs(bins[k].azimuth_deg - azimuth) < 1e-10:
                exact = bins[k]
                break
    else:
        exact = next((item for item in bins if abs(item.azimuth_deg - azimuth) < 1e-10), None)
    if exact is not None:
        complete = exact.coverage_status == "complete" and exact.elevation_rad is not None
        return InterpolatedHorizon(
            azimuth_deg=azimuth,
            elevation_rad=exact.elevation_rad,
            coverage_complete=complete,
            contributing_azimuths_deg=(exact.azimuth_deg,),
        )
    if len(bins) < 2:
        return InterpolatedHorizon(azimuth, None, False, (bins[0].azimuth_deg,))

    left_bin: HorizonBin
    right_bin: HorizonBin
    left_azimuth: float
    right_azimuth: float
    azimuth_for_interpolation: float
    if azimuth < bins[0].azimuth_deg:
        left_bin, right_bin = bins[-1], bins[0]
        left_azimuth = left_bin.azimuth_deg
        right_azimuth = right_bin.azimuth_deg + 360.0
        azimuth_for_interpolation = azimuth + 360.0
    elif azimuth > bins[-1].azimuth_deg:
        left_bin, right_bin = bins[-1], bins[0]
        left_azimuth = left_bin.azimuth_deg
        right_azimuth = right_bin.azimuth_deg + 360.0
        azimuth_for_interpolation = azimuth
    else:
        found: int | None = None
        if ascending:
            index = bisect_right(azimuths, azimuth) - 1
            if 0 <= index < len(bins) - 1 and azimuths[index] < azimuth < azimuths[index + 1]:
                found = index
        else:
            found = next((i for i in range(len(bins) - 1)
                          if bins[i].azimuth_deg < azimuth < bins[i + 1].azimuth_deg), None)
        if found is None:  # Defensive: should be unreachable once exact matches and wrap are handled.
            return InterpolatedHorizon(azimuth, None, False, ())
        left_bin, right_bin = bins[found], bins[found + 1]
        left_azimuth, right_azimuth = left_bin.azimuth_deg, right_bin.azimuth_deg
        azimuth_for_interpolation = azimuth

    if left_bin.elevation_rad is None or right_bin.elevation_rad is None:
        value = None
    else:
        fraction = (azimuth_for_interpolation - left_azimuth) / (right_azimuth - left_azimuth)
        value = left_bin.elevation_rad + fraction * (right_bin.elevation_rad - left_bin.elevation_rad)
    complete = (
        value is not None
        and left_bin.coverage_status == "complete"
        and right_bin.coverage_status == "complete"
    )
    return InterpolatedHorizon(
        azimuth_deg=azimuth,
        elevation_rad=value,
        coverage_complete=complete,
        contributing_azimuths_deg=(left_bin.azimuth_deg, right_bin.azimuth_deg),
    )
