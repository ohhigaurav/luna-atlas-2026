from __future__ import annotations

import math

import pytest

from lunar_core.visibility import (
    angular_semidiameter_rad,
    earth_centre_clear_margin_rad,
    earth_disc_visible_margin_rad,
    sun_upper_limb_margin_rad,
)


def test_prd_solar_margin_example_is_minus_1_034_degrees() -> None:
    # Choose a range/radius whose semidiameter rounds to the PRD's 0.266° worked value.
    semidiameter = math.radians(0.266)
    range_m = 1.0e9
    radius_m = range_m * math.sin(semidiameter)
    margin = sun_upper_limb_margin_rad(
        sun_elevation_rad=math.radians(-1.0),
        sun_range_m=range_m,
        sun_radius_m=radius_m,
        horizon_elevation_rad=math.radians(0.3),
    )
    assert math.degrees(margin) == pytest.approx(-1.034, abs=1e-9)
    assert margin < 0.0


def test_earth_centre_clearance_is_not_disc_visibility() -> None:
    centre_margin = earth_centre_clear_margin_rad(
        earth_elevation_rad=math.radians(-0.2),
        horizon_elevation_rad=math.radians(0.0),
        min_clearance_rad=0.0,
    )
    disc_margin = earth_disc_visible_margin_rad(
        earth_elevation_rad=math.radians(-0.2),
        earth_range_m=384_400_000.0,
        earth_radius_m=1_737_400.0,
        horizon_elevation_rad=math.radians(0.0),
    )
    assert centre_margin < 0.0
    assert disc_margin > 0.0


def test_clearance_margin_subtracts_configured_minimum() -> None:
    zero_margin = earth_centre_clear_margin_rad(
        earth_elevation_rad=math.radians(2),
        horizon_elevation_rad=math.radians(1),
    )
    margin_with_clearance = earth_centre_clear_margin_rad(
        earth_elevation_rad=math.radians(2),
        horizon_elevation_rad=math.radians(1),
        min_clearance_rad=math.radians(0.5),
    )
    assert math.degrees(zero_margin) == pytest.approx(1.0)
    assert math.degrees(margin_with_clearance) == pytest.approx(0.5)


def test_invalid_ranges_and_clearances_fail_closed() -> None:
    with pytest.raises(ValueError, match="greater than"):
        angular_semidiameter_rad(10.0, 10.0)
    with pytest.raises(ValueError, match="non-negative"):
        earth_centre_clear_margin_rad(
            earth_elevation_rad=0.0,
            horizon_elevation_rad=0.0,
            min_clearance_rad=-0.1,
        )
