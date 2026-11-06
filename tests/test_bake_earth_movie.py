"""Earth layer of the forecast (tools/bake_earth_movie.py) on synthetic terrain."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.bake_earth_movie import R_MOON, check_alignment, earth_frame_indices, earth_mask  # noqa: E402
from tools.shadow_match import Grid, from_stereo  # noqa: E402

EARTH_KM = 384_400.0


def flat_dem(half_m: float = 200_000.0, px: float = 1000.0, wall: tuple[float, float, float] | None = None) -> Grid:
    n = int(2 * half_m / px)
    c = -half_m + (np.arange(n) + 0.5) * px
    x, y = np.meshgrid(c, c[::-1])
    h = np.zeros_like(x)
    if wall is not None:  # a ridge along y = y0 for x in [x0, x1]... simplified: y >= y0 band of height H
        y0, width, height = wall
        h[(y >= y0) & (y < y0 + width)] = height
    return Grid(h, -half_m, half_m, px)


def earth_at(elev_deg: float, toward_lon_deg: float) -> np.ndarray:
    """Earth position (m) seen from the pole at a given elevation, toward a longitude."""
    e, lon = np.radians(elev_deg), np.radians(toward_lon_deg)
    horiz = np.array([np.cos(lon), np.sin(lon), 0.0])
    up = np.array([0.0, 0.0, -1.0])  # local up at the south pole
    d = np.cos(e) * horiz + np.sin(e) * up
    return np.array([0.0, 0.0, -R_MOON]) + EARTH_KM * 1000.0 * d


def test_flat_ground_sees_earth_above_and_not_below_horizon() -> None:
    dem = flat_dem()
    xs, ys = np.array([[0.0]]), np.array([[0.0]])
    assert earth_mask(dem, xs, ys, earth_at(+2.0, 0.0))[0, 0]
    # Well below the horizon: the ray dips into the sphere within the march range.
    assert not earth_mask(dem, xs, ys, earth_at(-2.0, 0.0))[0, 0]


def test_a_ridge_blocks_low_earth_on_its_side_only() -> None:
    # Ridge 1 km tall, 5 km north of the pole along +y (toward 0 E); Earth 2 deg up toward 0 E (+y).
    dem = flat_dem(wall=(5_000.0, 2_000.0, 1_000.0))
    xs, ys = np.array([[0.0]]), np.array([[0.0]])
    assert not earth_mask(dem, xs, ys, earth_at(2.0, 0.0))[0, 0]      # 1 km at 5 km = 11 deg > 2 deg
    assert earth_mask(dem, xs, ys, earth_at(2.0, 180.0))[0, 0]        # facing away from the ridge
    assert earth_mask(dem, xs, ys, earth_at(15.0, 0.0))[0, 0]         # high enough to clear it


def test_off_dem_is_never_visible() -> None:
    dem = flat_dem(half_m=10_000.0)
    assert not earth_mask(dem, np.array([[50_000.0]]), np.array([[0.0]]), earth_at(10.0, 0.0))[0, 0]


def test_topocentric_direction_matters() -> None:
    # A pixel 40 km from the pole sees Earth at a slightly different angle than the pole does; the
    # mask must use Earth's position, not a shared direction. Check via geometry, not the mask.
    p = from_stereo(np.array(40_000.0), np.array(0.0), np.array(0.0))
    e = earth_at(1.0, 90.0)
    d_topo = (e - p) / np.linalg.norm(e - p)
    d_centre = e / np.linalg.norm(e)
    angle = np.degrees(np.arccos(np.clip(d_topo @ d_centre, -1, 1)))
    assert 0.001 < angle < 0.3


def test_frame_indices_and_alignment() -> None:
    assert earth_frame_indices(10, 3) == [0, 3, 6, 9]
    with pytest.raises(ValueError):
        earth_frame_indices(10, 0)
    t0 = datetime(2027, 1, 1, tzinfo=UTC)
    times = [t0 + timedelta(hours=6 * k) for k in range(3)]
    check_alignment(times, ["2027-01-01T00:00:00Z", "2027-01-01T06:00:00.000Z", "2027-01-01T12:00:00Z", "x"][:3])
    with pytest.raises(SystemExit):
        check_alignment(times, ["2027-01-01T00:00:00Z", "2027-01-01T07:00:00Z", "2027-01-01T12:00:00Z"])
    with pytest.raises(SystemExit):
        check_alignment(times, ["2027-01-01T00:00:00Z"])


def test_check_tool_helpers() -> None:
    from tools import check_earth_movie as cem

    lat, lon = cem.stereo_to_latlon(0.0, 30_320.0)  # ~1 deg from the pole toward 0 E
    assert lat == pytest.approx(-89.0, abs=0.01) and lon == pytest.approx(0.0, abs=1e-9)
    assert cem.stereo_to_latlon(-11_380.0, -12_120.0)[1] == pytest.approx(223.2, abs=0.05)
    assert cem._second("2027-01-30T23:59:59.999Z") == cem._second("2027-01-31T00:00:00Z")
    share = np.array([[0.0, 0.5], [1.0, 0.25]])
    picks = cem.pick_pixels(share, np.ones_like(share, bool))
    mixed = [(r, c) for r, c, lab in picks if lab == "mixed"]
    assert sorted(mixed) == [(0, 1), (1, 1)]  # only two mixed pixels exist
    assert picks == cem.pick_pixels(share, np.ones_like(share, bool))  # seeded
    good = cem.score([(True, True, 2.0), (False, False, -1.0), (True, False, 0.1)])
    assert good["agreement"] == pytest.approx(2 / 3) and good["agreement_clear"] == 1.0 and not good["pass"]
    assert cem.score([(True, True, 2.0)] * 99 + [(True, False, 0.1)])["pass"]
    assert cem.score([(True, True, 2.0)] * 99 + [(True, False, 0.6)])["pass"]  # 99% clear: at the limit
    assert not cem.score([(True, True, 2.0)] * 98 + [(True, False, 0.6)] * 2)["pass"]
