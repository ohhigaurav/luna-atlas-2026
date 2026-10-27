from __future__ import annotations

import math
from typing import Any, Sequence

import pytest

from lunar_core.geometry import ObserverSite, SpiceGeometry


class FakeSpice:
    def __init__(self) -> None:
        self.utc_calls: list[str] = []
        self.az_calls: list[tuple[Any, ...]] = []
        self.radii_km = (1_737.4, 1_737.4, 1_737.4)

    def bodvrd(self, body: str, item: str, maxn: int) -> tuple[int, Any]:
        assert body == "MOON"
        assert item == "RADII"
        assert maxn == 3
        return 3, self.radii_km

    def utc2et(self, utcstr: str) -> float:
        self.utc_calls.append(utcstr)
        return float(len(self.utc_calls) * 100.0)

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
    ) -> tuple[Any, float]:
        self.az_calls.append((method, target, et, abcorr, azccw, elplsz, tuple(obspos), obsctr, obsref))
        return [384_400.0, math.radians(90.0), math.radians(-0.2), 0.0, 0.0, 0.0], 1.28


def test_loaded_pck_radii_and_explicit_frame_build_geometry() -> None:
    spice = FakeSpice()
    geometry = SpiceGeometry.from_loaded_spice_kernels(
        spice,
        frame="MOON_ME",
        observer_center="MOON",
        aberration_correction="LT+S",
    )

    assert geometry.reference_radius_m == pytest.approx(1_737_400.0)
    assert geometry.frame == "MOON_ME"
    assert geometry.aberration_correction == "LT+S"


def test_geometry_calls_azlcpo_at_surface_point_and_converts_units() -> None:
    spice = FakeSpice()
    geometry = SpiceGeometry.from_loaded_spice_kernels(
        spice,
        frame="MOON_ME",
        observer_center="MOON",
        aberration_correction="LT+S",
    )
    site = ObserverSite(
        site_id="synthetic-geometry-test",
        latitude_deg=-90.0,
        longitude_deg=0.0,
        latitude_type="planetocentric",
        site_ground_elevation_m=10.0,
    )

    result = geometry.direction(
        site,
        "2027-01-01T00:00:00Z",
        target="EARTH",
        observer_height_m=2.0,
    )

    assert result.utc == "2027-01-01T00:00:00Z"
    assert result.ephemeris_time_s == 100.0
    assert result.range_m == pytest.approx(384_400_000.0)
    assert result.azimuth_deg == pytest.approx(90.0)
    assert result.elevation_rad == pytest.approx(math.radians(-0.2))
    assert result.light_time_s == pytest.approx(1.28)
    call = spice.az_calls[0]
    assert call[:6] == ("ELLIPSOID", "EARTH", 100.0, "LT+S", False, True)
    assert call[7:] == ("MOON", "MOON_ME")
    assert call[6][2] == pytest.approx(-(1_737_400 + 10 + 2) / 1_000)


def test_batch_returns_one_direction_per_epoch_with_same_contract() -> None:
    spice = FakeSpice()
    geometry = SpiceGeometry.from_loaded_spice_kernels(
        spice,
        frame="MOON_ME",
        observer_center="MOON",
        aberration_correction="LT+S",
    )
    site = ObserverSite("synthetic-batch", 0.0, 0.0, "planetographic")
    results = geometry.directions(
        site,
        ["2027-01-01T00:00:00Z", "2027-01-01T00:30:00+00:00"],
        target="SUN",
        observer_height_m=2.0,
    )
    assert len(results) == 2
    assert [row.ephemeris_time_s for row in results] == [100.0, 200.0]
    assert [row.target for row in results] == ["SUN", "SUN"]
    assert len(spice.az_calls) == 2
    assert spice.utc_calls == ["2027-01-01T00:00:00Z", "2027-01-01T00:30:00Z"]


def test_non_spherical_radii_fail_closed() -> None:
    spice = FakeSpice()
    spice.radii_km = (1_737.4, 1_736.0, 1_737.4)
    with pytest.raises(NotImplementedError, match="equal lunar PCK radii"):
        SpiceGeometry.from_loaded_spice_kernels(
            spice,
            frame="MOON_ME",
            observer_center="MOON",
            aberration_correction="LT+S",
        )


def test_time_must_be_utc_and_observer_height_valid() -> None:
    spice = FakeSpice()
    geometry = SpiceGeometry.from_loaded_spice_kernels(
        spice,
        frame="MOON_ME",
        observer_center="MOON",
        aberration_correction="LT+S",
    )
    site = ObserverSite("synthetic-utc-test", 0.0, 0.0, "planetocentric")
    with pytest.raises(ValueError, match="non-zero offsets"):
        geometry.direction(
            site, "2027-01-01T05:30:00+05:30", target="SUN", observer_height_m=2.0
        )
    with pytest.raises(ValueError, match="non-negative"):
        geometry.direction(
            site, "2027-01-01T00:00:00Z", target="SUN", observer_height_m=-1.0
        )
