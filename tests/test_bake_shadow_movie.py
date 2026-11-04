from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from tools import bake_shadow_movie as movie
from tools.shadow_match import Grid, from_stereo


def _xy() -> tuple[np.ndarray, np.ndarray]:
    return np.meshgrid(np.array([-1000.0, 0.0, 1000.0]), np.array([1000.0, 0.0, -1000.0]))


def test_flat_ground_normal_is_radial() -> None:
    dem = Grid(np.zeros((200, 200)), x0=-20_000.0, y0=20_000.0, px=200.0)
    xs, ys = _xy()
    n = movie.surface_normals(dem, xs, ys, 100.0)
    up = from_stereo(xs, ys, np.zeros_like(xs))
    up /= np.linalg.norm(up, axis=-1, keepdims=True)
    assert np.allclose(np.sum(n * up, axis=-1), 1.0, atol=1e-6)


def test_slope_rising_toward_plus_y_tilts_normal_toward_minus_y() -> None:
    rows_y = 20_000.0 - (np.arange(200) + 0.5) * 200.0
    h = np.tile((0.1 * rows_y)[:, None], (1, 200))  # 10% grade rising toward +y
    dem = Grid(h, x0=-20_000.0, y0=20_000.0, px=200.0)
    n = movie.surface_normals(dem, np.array([0.0]), np.array([0.0]), 100.0)[0]
    # at the pole, +y (toward 0 E) is MOON_ME +X; the normal leans away from the rise: negative X component
    assert n[0] == pytest.approx(-0.1 / np.sqrt(1.01), abs=2e-3)


def test_shade_is_zero_in_shadow_and_brightest_facing_the_sun() -> None:
    normals = np.array([[[0, 0, -1.0], [0.6, 0, -0.8]]])
    sun = np.array([0.6, 0.0, -0.8])
    img = movie.shade(np.array([[True, True]]), normals, sun, gamma=1.0)
    assert img[0, 1] == 255 and 0 < img[0, 0] < 255
    assert movie.shade(np.array([[False, True]]), normals, sun)[0, 0] == 0


def test_frame_times() -> None:
    t = movie.frame_times(datetime(2027, 1, 1, tzinfo=UTC), 1, 2)
    assert len(t) == 12 and t[-1].hour == 22
