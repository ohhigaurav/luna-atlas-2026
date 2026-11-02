"""The cached/bisect horizon look-ups must return exactly what the original linear scans returned.

The original implementation is kept verbatim in tests/fixtures/horizon_reference.py.
"""
from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

import pytest
from lunar_core import horizon as fast
from lunar_core.horizon import HorizonBin, TerrainHorizon

_spec = importlib.util.spec_from_file_location("horizon_reference", Path(__file__).parent / "fixtures" / "horizon_reference.py")
ref = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
sys.modules["horizon_reference"] = ref  # dataclasses look their module up here
_spec.loader.exec_module(ref)  # type: ignore[union-attr]


def _horizon(n: int, seed: int, holes: int = 0, uniform: bool = True) -> TerrainHorizon:
    rng = random.Random(seed)
    if uniform:
        az = [i * 360.0 / n for i in range(n)]
    else:
        az = sorted(rng.uniform(0, 360) for _ in range(n))
    gaps = set(rng.sample(range(n), holes))
    bins = tuple(HorizonBin(a, None if i in gaps else rng.uniform(-0.02, 0.05), 50.0,
                            "none" if i in gaps else rng.choice(["complete", "complete", "incomplete"]), 10, 0)
                 for i, a in enumerate(az))
    return TerrainHorizon(1_737_400.0, 1_737_402.0, 2.0, 200_000.0, bins)


def _as_ref(h: TerrainHorizon):  # same values, reference module's dataclasses
    return ref.TerrainHorizon(h.reference_radius_m, h.observer_radius_m, h.observer_height_m, h.max_range_m,
                              tuple(ref.HorizonBin(b.azimuth_deg, b.elevation_rad, b.controlling_distance_m,
                                                   b.coverage_status, b.sample_count, b.nodata_count) for b in h.bins))


@pytest.mark.parametrize(("n", "seed", "holes", "uniform"), [(720, 1, 0, True), (720, 2, 5, True), (72, 3, 2, True),
                                                             (2, 4, 0, True), (1, 5, 0, True), (50, 6, 3, False)])
def test_interpolation_identical(n: int, seed: int, holes: int, uniform: bool) -> None:
    h = _horizon(n, seed, holes, uniform)
    r = _as_ref(h)
    rng = random.Random(seed + 100)
    probes = [rng.uniform(-720, 720) for _ in range(3000)] + [b.azimuth_deg for b in h.bins] + \
             [b.azimuth_deg + 5e-11 for b in h.bins] + [0.0, 360.0, 359.9999999, -1e-12]
    for az in probes:
        a, b = fast.interpolate_horizon(h, az), ref.interpolate_horizon(r, az)
        assert (a.azimuth_deg, a.elevation_rad, a.coverage_complete, a.contributing_azimuths_deg) == \
               (b.azimuth_deg, b.elevation_rad, b.coverage_complete, b.contributing_azimuths_deg), az


@pytest.mark.parametrize(("n", "seed", "holes"), [(720, 1, 0), (720, 2, 4), (72, 3, 1), (2, 4, 0)])
def test_slope_bound_identical(n: int, seed: int, holes: int) -> None:
    h = _horizon(n, seed, holes)
    r = _as_ref(h)
    rng = random.Random(seed)
    for _ in range(2000):
        a, b = rng.uniform(-400, 400), rng.uniform(-400, 400)
        assert fast.horizon_slope_bound_rad_per_deg(h, a, b) == ref.horizon_slope_bound_rad_per_deg(r, a, b)


def test_non_uniform_slope_bound_still_raises_and_cache_never_mixes_horizons() -> None:
    with pytest.raises(ValueError, match="uniformly spaced"):
        fast.horizon_slope_bound_rad_per_deg(_horizon(50, 6, 0, uniform=False), 10, 20)
    for seed in range(40):  # more horizons than the cache holds; each must use its own tables
        h = _horizon(36, seed)
        assert fast.horizon_slope_bound_rad_per_deg(h, 0, 359) == ref.horizon_slope_bound_rad_per_deg(_as_ref(h), 0, 359)
