from __future__ import annotations

import math

import pytest
from lunar_core.horizon import (
    TerrainSample,
    calculate_terrain_horizon,
    flat_horizon_elevation_rad,
    interpolate_horizon,
)

RADIUS_M = 1_737_400.0


def test_flat_horizon_matches_prd_analytic_dip() -> None:
    for height in (0.0, 0.1, 2.0, 20.0, 100.0):
        actual = flat_horizon_elevation_rad(RADIUS_M, height)
        expected = -math.acos(RADIUS_M / (RADIUS_M + height))
        assert actual == pytest.approx(expected, abs=1e-12)


def test_ridge_controls_horizon_and_returns_its_distance() -> None:
    rays = {
        0.0: [
            TerrainSample(0.0, 0.0),
            TerrainSample(100.0, 0.0),
            TerrainSample(1_000.0, 0.0),
            TerrainSample(2_000.0, 80.0),
            TerrainSample(3_000.0, 0.0),
        ]
    }
    result = calculate_terrain_horizon(
        rays,
        reference_radius_m=RADIUS_M,
        observer_height_m=2.0,
        max_range_m=3_000.0,
    )
    bin0 = result.bins[0]
    assert bin0.coverage_status == "complete"
    assert bin0.controlling_distance_m == 2_000.0
    assert bin0.elevation_rad is not None


def test_far_rim_can_control_horizon_over_a_nearer_ridge() -> None:
    result = calculate_terrain_horizon(
        {0.0: [
            TerrainSample(0.0, 0.0),
            TerrainSample(1_000.0, 20.0),
            TerrainSample(10_000.0, 300.0),
        ]},
        reference_radius_m=RADIUS_M,
        observer_height_m=2.0,
        max_range_m=10_000.0,
    )
    assert result.bins[0].coverage_status == "complete"
    assert result.bins[0].controlling_distance_m == 10_000.0


def test_ray_that_does_not_cover_origin_and_declared_range_is_incomplete() -> None:
    result = calculate_terrain_horizon(
        {0.0: [TerrainSample(100.0, 0.0), TerrainSample(500.0, 0.0)]},
        reference_radius_m=RADIUS_M,
        max_range_m=1_000.0,
    )
    assert result.bins[0].coverage_status == "incomplete"


def test_observer_height_changes_flat_sphere_dip() -> None:
    one_metre = flat_horizon_elevation_rad(RADIUS_M, 1.0)
    two_metres = flat_horizon_elevation_rad(RADIUS_M, 2.0)
    assert two_metres < one_metre < 0.0


def test_nodata_never_silently_becomes_flat_terrain() -> None:
    result = calculate_terrain_horizon(
        {90.0: [TerrainSample(100, 0.0), TerrainSample(200, None), TerrainSample(300, 0.0)]},
        reference_radius_m=RADIUS_M,
        max_range_m=300,
    )
    bin90 = result.bins[0]
    assert bin90.coverage_status == "incomplete"
    assert bin90.nodata_count == 1
    assert bin90.elevation_rad is not None  # Known terrain retained for diagnostics only.

    interpolated = interpolate_horizon(result, 90)
    assert not interpolated.coverage_complete


def test_all_nodata_ray_has_no_numeric_horizon() -> None:
    result = calculate_terrain_horizon(
        {180.0: [TerrainSample(100, None)]},
        reference_radius_m=RADIUS_M,
        max_range_m=200,
    )
    assert result.bins[0].coverage_status == "none"
    assert result.bins[0].elevation_rad is None


def test_horizon_interpolation_wraps_through_zero_degrees() -> None:
    result = calculate_terrain_horizon(
        {
            90.0: [TerrainSample(0, 0.0), TerrainSample(100, 0.0)],
            270.0: [TerrainSample(0, 0.0), TerrainSample(100, 20.0)],
        },
        reference_radius_m=RADIUS_M,
        max_range_m=100,
    )
    at_zero = interpolate_horizon(result, 0.0)
    assert at_zero.elevation_rad is not None
    assert at_zero.coverage_complete
    # The 0° direction lies halfway between the 270° and 90° bins.
    expected = (
        result.bins[0].elevation_rad + result.bins[1].elevation_rad
    ) / 2.0
    assert at_zero.elevation_rad == pytest.approx(expected)


def test_invalid_rays_fail_instead_of_being_normalised_silently() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        calculate_terrain_horizon(
            {0.0: [TerrainSample(200, 0.0), TerrainSample(100, 0.0)]},
            reference_radius_m=RADIUS_M,
            max_range_m=300,
        )
    with pytest.raises(ValueError, match="duplicate azimuth"):
        calculate_terrain_horizon(
            {0.0: [TerrainSample(100, 0.0)], 360.0: [TerrainSample(100, 0.0)]},
            reference_radius_m=RADIUS_M,
            max_range_m=100,
        )


def _uniform_horizon(elevations):
    from lunar_core.horizon import HorizonBin, TerrainHorizon
    step = 360.0 / len(elevations)
    return TerrainHorizon(
        reference_radius_m=1_737_400.0, observer_radius_m=1_737_402.0, observer_height_m=2.0,
        max_range_m=200_000.0,
        bins=tuple(
            HorizonBin(azimuth_deg=i * step, elevation_rad=value, controlling_distance_m=1.0,
                       coverage_status="complete", sample_count=1, nodata_count=0)
            for i, value in enumerate(elevations)
        ),
    )


def test_slope_bound_is_local_and_handles_wrap() -> None:
    from lunar_core.horizon import horizon_slope_bound_rad_per_deg

    elevations = [0.0] * 720
    elevations[100] = 0.05  # spike at 50 deg: slope 0.1 rad/deg on both sides
    elevations[719] = 0.02  # step across north: slope 0.04 rad/deg
    horizon = _uniform_horizon(elevations)
    assert horizon_slope_bound_rad_per_deg(horizon, 49.6, 50.4) == pytest.approx(0.1)
    assert horizon_slope_bound_rad_per_deg(horizon, 200.0, 201.0) == 0.0
    assert horizon_slope_bound_rad_per_deg(horizon, 359.8, 0.2) == pytest.approx(0.04)
    assert horizon_slope_bound_rad_per_deg(horizon, 0.2, 359.8) == pytest.approx(0.04)
    # The shorter arc decides: 10 -> 130 passes the spike; 10 -> 250 goes the other way via north.
    assert horizon_slope_bound_rad_per_deg(horizon, 10.0, 130.0) == pytest.approx(0.1)
    assert horizon_slope_bound_rad_per_deg(horizon, 10.0, 250.0) == pytest.approx(0.04)


def test_slope_bound_over_missing_terrain_is_infinite() -> None:
    from lunar_core.horizon import horizon_slope_bound_rad_per_deg

    elevations = [0.0] * 720
    elevations[10] = None
    horizon = _uniform_horizon(elevations)
    assert horizon_slope_bound_rad_per_deg(horizon, 4.0, 6.0) == float("inf")
    assert horizon_slope_bound_rad_per_deg(horizon, 100.0, 101.0) == 0.0
