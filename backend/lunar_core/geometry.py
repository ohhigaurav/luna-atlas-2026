"""SPICE-backed topocentric Sun/Earth directions for a spherical Moon.

This module uses ``azlcpo`` so the observer is the specified surface point rather than the
Moon's centre. Its kernel pool is process-global, so every CSPICE call is serialized under one
module-level lock. Kernels must be loaded and hash/coverage-checked by the caller before use.

The implementation intentionally fails closed for a non-spherical Moon. The current PRD says
latitude-type differences are immaterial only while the selected lunar PCK radii are equal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import cos, degrees, isfinite, radians, sin
from typing import Any, Literal, Protocol, Sequence, cast

from lunar_core.spice_runtime import SPICE_LOCK

TargetName = Literal["SUN", "EARTH"]
LatitudeType = Literal["planetocentric", "planetographic"]



class SpiceAdapter(Protocol):
    """Small protocol that permits unit tests without requiring loaded kernels."""

    def utc2et(self, utcstr: str) -> float: ...

    def azlcpo(
        self,
        method: str,
        target: str,
        et: float,
        abcorr: str,
        azccw: bool,
        elplsz: bool,
        obspos: Sequence[float],
        obsctr: str,
        obsref: str,
    ) -> tuple[Any, float]: ...

    def bodvrd(self, body: str, item: str, maxn: int) -> tuple[int, Any]: ...


@dataclass(frozen=True, slots=True)
class ObserverSite:
    site_id: str
    latitude_deg: float
    longitude_deg: float
    latitude_type: LatitudeType
    site_ground_elevation_m: float = 0.0
    longitude_direction: Literal["east_positive"] = "east_positive"

    def __post_init__(self) -> None:
        if not self.site_id.strip():
            raise ValueError("site_id must not be empty")
        for name, value in (
            ("latitude_deg", self.latitude_deg),
            ("longitude_deg", self.longitude_deg),
            ("site_ground_elevation_m", self.site_ground_elevation_m),
        ):
            if not isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not -90.0 <= self.latitude_deg <= 90.0:
            raise ValueError("latitude_deg must be within [-90, 90]")
        if not -360.0 <= self.longitude_deg <= 360.0:
            raise ValueError("longitude_deg must be within [-360, 360]")


@dataclass(frozen=True, slots=True)
class TargetDirection:
    site_id: str
    target: TargetName
    utc: str
    ephemeris_time_s: float
    range_m: float
    azimuth_deg: float
    elevation_rad: float
    light_time_s: float
    frame: str
    aberration_correction: str
    # d(azimuth)/dt and d(elevation)/dt from azlcpo's state (rad/s). None when the adapter did not
    # return velocity components; event discovery then cannot be certified.
    azimuth_rate_rad_s: float | None = None
    elevation_rate_rad_s: float | None = None


def _rates_from_state(state: Any) -> tuple[float | None, float | None]:
    """azlcpo returns [range, az, el, d(range)/dt, d(az)/dt, d(el)/dt] in km, rad, rad/s."""
    try:
        if len(state) < 6:
            return None, None
        az_rate, el_rate = float(state[4]), float(state[5])
    except (TypeError, ValueError):
        return None, None
    if not (isfinite(az_rate) and isfinite(el_rate)):
        return None, None
    return az_rate, el_rate


class SpiceGeometry:
    """Compute local azimuth/elevation/range using SPICE's constant-point observer API.

    ``body_radii_m`` must come from the loaded lunar PCK. ``reference_radius_m`` is the radius
    used in the DEM/site datum contract and must agree with the spherical PCK radius.
    ``aberration_correction`` and ``frame`` are required constructor arguments so the selected
    frame chain and apparent/ geometric convention cannot be hidden defaults.
    """

    def __init__(
        self,
        spice: SpiceAdapter,
        *,
        reference_radius_m: float,
        body_radii_m: tuple[float, float, float],
        frame: str,
        observer_center: str,
        aberration_correction: str,
        radius_tolerance_m: float = 1e-3,
    ) -> None:
        if not isfinite(reference_radius_m) or reference_radius_m <= 0:
            raise ValueError("reference_radius_m must be finite and positive")
        if len(body_radii_m) != 3 or any(
            not isfinite(radius) or radius <= 0 for radius in body_radii_m
        ):
            raise ValueError("body_radii_m must contain three finite positive radii")
        if not isfinite(radius_tolerance_m) or radius_tolerance_m < 0:
            raise ValueError("radius_tolerance_m must be finite and non-negative")
        if max(body_radii_m) - min(body_radii_m) > radius_tolerance_m:
            raise NotImplementedError(
                "planetographic/planetocentric handling requires an oblate-body implementation; "
                "this prototype only supports equal lunar PCK radii"
            )
        mean_radius_m = sum(body_radii_m) / 3.0
        if abs(mean_radius_m - reference_radius_m) > radius_tolerance_m:
            raise ValueError("reference_radius_m must agree with the loaded PCK radius")
        if not frame.strip() or not observer_center.strip() or not aberration_correction.strip():
            raise ValueError("frame, observer_center and aberration_correction are required")

        self._spice = spice
        self.reference_radius_m = reference_radius_m
        self.body_radii_m = body_radii_m
        self.frame = frame
        self.observer_center = observer_center
        self.aberration_correction = aberration_correction
        self.radius_tolerance_m = radius_tolerance_m

    @classmethod
    def from_loaded_spice_kernels(
        cls,
        spice: SpiceAdapter,
        *,
        frame: str,
        observer_center: str,
        aberration_correction: str,
        radius_tolerance_m: float = 1e-3,
    ) -> "SpiceGeometry":
        """Read lunar radii from the already-loaded PCK and enforce the spherical contract."""
        with SPICE_LOCK:
            dimension, radii_km = spice.bodvrd("MOON", "RADII", 3)
        if dimension != 3:
            raise ValueError(f"expected 3 lunar radii from PCK, received dimension={dimension}")
        radii_values = tuple(float(radii_km[index]) * 1_000.0 for index in range(3))
        body_radii_m = (radii_values[0], radii_values[1], radii_values[2])
        reference_radius_m = sum(body_radii_m) / 3.0
        return cls(
            spice,
            reference_radius_m=reference_radius_m,
            body_radii_m=body_radii_m,
            frame=frame,
            observer_center=observer_center,
            aberration_correction=aberration_correction,
            radius_tolerance_m=radius_tolerance_m,
        )

    @classmethod
    def from_spiceypy(
        cls,
        *,
        frame: str,
        observer_center: str,
        aberration_correction: str,
        radius_tolerance_m: float = 1e-3,
    ) -> "SpiceGeometry":
        """Build from SpiceyPy after the application has loaded and preflighted its kernels."""
        try:
            import spiceypy
        except ImportError as exc:  # pragma: no cover - dependency is part of the locked project
            raise RuntimeError("SpiceyPy is required for SPICE geometry; install project deps") from exc
        adapter = cast(SpiceAdapter, spiceypy)
        return cls.from_loaded_spice_kernels(
            adapter,
            frame=frame,
            observer_center=observer_center,
            aberration_correction=aberration_correction,
            radius_tolerance_m=radius_tolerance_m,
        )

    def observer_position_km(self, site: ObserverSite, observer_height_m: float) -> tuple[float, float, float]:
        """Return the surface point in the declared body-fixed frame, relative to the centre."""
        if not isfinite(observer_height_m) or observer_height_m < 0:
            raise ValueError("observer_height_m must be finite and non-negative")
        radius_m = self.reference_radius_m + site.site_ground_elevation_m + observer_height_m
        if radius_m <= 0:
            raise ValueError("observer radius must be positive")
        latitude = radians(site.latitude_deg)
        longitude = radians(site.longitude_deg)
        radius_km = radius_m / 1_000.0
        # Equal PCK radii make planetocentric and planetographic latitudes equivalent. If the
        # PCK is not spherical, construction fails before this formula can be used.
        return (
            radius_km * cos(latitude) * cos(longitude),
            radius_km * cos(latitude) * sin(longitude),
            radius_km * sin(latitude),
        )

    @staticmethod
    def _normalise_utc(utc_iso: str) -> str:
        try:
            parsed = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("time must be a valid UTC ISO 8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("time must include a UTC timezone")
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("time must be UTC; non-zero offsets are not accepted")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def directions(
        self,
        site: ObserverSite,
        utc_times: Sequence[str],
        *,
        target: TargetName,
        observer_height_m: float,
    ) -> tuple[TargetDirection, ...]:
        """Calculate a time series for SUN or EARTH, serialized under the global SPICE lock."""
        if target not in ("SUN", "EARTH"):
            raise ValueError("target must be 'SUN' or 'EARTH'")
        observer_position = self.observer_position_km(site, observer_height_m)
        results: list[TargetDirection] = []
        with SPICE_LOCK:
            for utc_input in utc_times:
                utc = self._normalise_utc(utc_input)
                et = float(self._spice.utc2et(utc))
                if not isfinite(et):
                    raise ValueError(f"SPICE utc2et returned a non-finite epoch for {utc}")
                # NAIF azlcpo: method, target, et, abcorr, azccw, elplsz, obspos, obsctr, obsref.
                # azccw=False gives clockwise azimuth from local north under the PRD convention;
                # elplsz=True measures elevation above the local tangent plane.
                state, light_time = self._spice.azlcpo(
                    "ELLIPSOID",
                    target,
                    et,
                    self.aberration_correction,
                    False,
                    True,
                    observer_position,
                    self.observer_center,
                    self.frame,
                )
                if len(state) < 3:
                    raise ValueError("SPICE azlcpo returned fewer than 3 position components")
                range_km, azimuth_rad, elevation_rad = (
                    float(state[0]), float(state[1]), float(state[2])
                )
                light_time = float(light_time)
                if not all(isfinite(value) for value in (
                    range_km, azimuth_rad, elevation_rad, light_time
                )) or range_km <= 0:
                    raise ValueError(f"SPICE azlcpo returned an invalid state for {target} at {utc}")
                az_rate, el_rate = _rates_from_state(state)
                results.append(TargetDirection(
                    site_id=site.site_id,
                    target=target,
                    utc=utc,
                    ephemeris_time_s=et,
                    range_m=range_km * 1_000.0,
                    azimuth_deg=degrees(azimuth_rad) % 360.0,
                    elevation_rad=elevation_rad,
                    light_time_s=light_time,
                    frame=self.frame,
                    aberration_correction=self.aberration_correction,
                    azimuth_rate_rad_s=az_rate,
                    elevation_rate_rad_s=el_rate,
                ))
        return tuple(results)

    def direction(
        self,
        site: ObserverSite,
        utc_time: str,
        *,
        target: TargetName,
        observer_height_m: float,
    ) -> TargetDirection:
        """Single-epoch convenience wrapper around the batched implementation."""
        return self.directions(
            site, [utc_time], target=target, observer_height_m=observer_height_m
        )[0]

    def utc_to_et(self, utc_time: str) -> float:
        """Convert a UTC ISO-8601 epoch to SPICE ET under the global kernel-pool lock."""
        utc = self._normalise_utc(utc_time)
        with SPICE_LOCK:
            et = float(self._spice.utc2et(utc))
        if not isfinite(et):
            raise ValueError(f"SPICE utc2et returned a non-finite epoch for {utc}")
        return et

    def et_to_utc(self, et: float, *, precision: int = 3) -> str:
        """Format TDB ET as UTC ISO-8601 using the loaded LSK."""
        if not isfinite(et):
            raise ValueError("ET must be finite")
        formatter = getattr(self._spice, "et2utc", None)
        if formatter is None:
            raise RuntimeError("SPICE adapter does not provide et2utc conversion")
        with SPICE_LOCK:
            formatted = str(formatter(float(et), "ISOC", precision))
        # CSPICE normally returns YYYY-MM-DDTHH:MM:SS.sss without a trailing Z.
        return formatted.rstrip("Z") + "Z"

    def direction_at_et(
        self,
        site: ObserverSite,
        et: float,
        *,
        target: TargetName,
        observer_height_m: float,
    ) -> TargetDirection:
        """Calculate target direction directly at a TDB ET epoch (for root refinement).

        Event-solving time remains ET; it is never passed as a UTC timestamp. The LSK is used
        only when producing the returned UTC label.
        """
        if target not in ("SUN", "EARTH"):
            raise ValueError("target must be 'SUN' or 'EARTH'")
        if not isfinite(et):
            raise ValueError("ET must be finite")
        observer_position = self.observer_position_km(site, observer_height_m)
        with SPICE_LOCK:
            state, light_time = self._spice.azlcpo(
                "ELLIPSOID", target, float(et), self.aberration_correction,
                False, True, observer_position, self.observer_center, self.frame,
            )
            range_km, azimuth_rad, elevation_rad = (
                float(state[0]), float(state[1]), float(state[2])
            )
            light_time = float(light_time)
            if not all(isfinite(value) for value in (
                range_km, azimuth_rad, elevation_rad, light_time
            )) or range_km <= 0:
                raise ValueError(f"SPICE azlcpo returned an invalid state for {target} at ET={et}")
            formatter = getattr(self._spice, "et2utc", None)
            utc = (str(formatter(float(et), "ISOC", 3)).rstrip("Z") + "Z") if formatter else ""
        az_rate, el_rate = _rates_from_state(state)
        return TargetDirection(
            site_id=site.site_id, target=target, utc=utc, ephemeris_time_s=float(et),
            range_m=range_km * 1_000.0, azimuth_deg=degrees(azimuth_rad) % 360.0,
            elevation_rad=elevation_rad, light_time_s=light_time, frame=self.frame,
            aberration_correction=self.aberration_correction,
            azimuth_rate_rad_s=az_rate, elevation_rate_rad_s=el_rate,
        )
