"""Pure helpers of tools/check_sky_orientation.py (the real-kernel and Horizons parts run on a development machine)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import check_sky_orientation as cso  # noqa: E402


def rot_z(a_deg: float) -> list[list[float]]:
    a = math.radians(a_deg)
    return [[math.cos(a), math.sin(a), 0.0], [-math.sin(a), math.cos(a), 0.0], [0.0, 0.0, 1.0]]


def test_centric_to_detic() -> None:
    assert cso.centric_to_detic_deg(0.0) == 0.0
    assert cso.centric_to_detic_deg(-90.0) == -90.0
    # Largest difference near 45 deg: about 0.19 deg for Earth.
    assert cso.centric_to_detic_deg(45.0) - 45.0 == pytest.approx(0.192, abs=0.002)
    assert cso.centric_to_detic_deg(-20.0) < -20.0


def test_angle_and_orthonormal() -> None:
    assert cso.angle_deg([1.0, 0.0, 0.0], [0.0, 2.0, 0.0]) == pytest.approx(90.0)
    assert cso.angle_deg([1.0, 0.0, 0.0], [1.0, 1e-9, 0.0]) == pytest.approx(math.degrees(1e-9), rel=1e-6)
    assert cso.orthonormal_error(rot_z(33.0)) < 1e-15
    assert cso.orthonormal_error([[1.0, 0.0, 0.0], [0.0, 1.0, 1e-6], [0.0, 0.0, 1.0]]) == pytest.approx(1e-6)


def test_pole_and_spin_rate() -> None:
    ra, dec = cso.pole_ra_dec(rot_z(10.0))
    assert dec == pytest.approx(90.0)
    # Pole at RA 270, Dec 66.5: build M whose third row is that direction.
    ra0, dec0 = math.radians(270.0), math.radians(66.5)
    z = [math.cos(dec0) * math.cos(ra0), math.cos(dec0) * math.sin(ra0), math.sin(dec0)]
    assert cso.pole_ra_dec([[1, 0, 0], [0, 1, 0], z]) == pytest.approx((270.0, 66.5))
    # Frame spinning +13.176 deg/day about J2000 +Z: v_frame = Rz(-angle) v, i.e. M = rot_z(angle).
    days = [0.0, 0.25, 0.5, 0.75, 1.0, 1.25]
    mats = [rot_z(13.176 * d) for d in days]
    rate = cso.spin_rate_deg_per_day(mats, [d * 86_400.0 for d in days])
    assert abs(rate) == pytest.approx(13.176, rel=1e-6)


def test_parse_sub_observer_multirow() -> None:
    text = "\n".join([
        "header junk",
        " Date__(UT)__HR:MN:SC.fff, , , ObsSub-LON, ObsSub-LAT,",
        "*******",
        "$$SOE",
        " 2027-Jan-01 00:00:00.000, , , -75.123456, -21.5,",
        " 2027-Jan-31 00:00:00.000, , , 120.5, 18.25,",
        "$$EOE",
    ])
    assert cso.parse_sub_observer(text) == [(pytest.approx(284.876544), -21.5), (120.5, 18.25)]
    with pytest.raises(ValueError):
        cso.parse_sub_observer("no table")


def test_horizons_params() -> None:
    p = cso.horizons_params([2461406.5, 2461436.5])
    assert p["COMMAND"] == "'399'" and p["CENTER"] == "'500@301'" and p["QUANTITIES"] == "'14'"
    assert p["TLIST"].split("\n") == ["2461406.500000000", "2461436.500000000"]


def test_iau_moon_pole() -> None:
    ra, dec = cso.iau_moon_pole(0.0)  # J2000: E1 = 125.045 deg
    assert ra == pytest.approx(269.9949 - 3.8787 * math.sin(math.radians(125.045)), abs=0.2)
    assert dec == pytest.approx(66.5392 + 1.5419 * math.cos(math.radians(125.045)), abs=0.1)
    # 2027 (d ~ 9862): the 18.6-year term moves the pole to RA ~272.4-273.4, Dec ~67.4-67.8.
    ra27, dec27 = cso.iau_moon_pole(9861.5)
    assert 272.0 < ra27 < 273.6 and 67.3 < dec27 < 67.9
    assert cso.angle_deg(cso.radec_unit(ra27, dec27), cso.radec_unit(ra27, dec27)) == 0.0
