"""Helpers of tools/find_summit.py."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.find_summit import from_stereo, to_stereo, top_spots  # noqa: E402


def test_stereo_round_trip() -> None:
    for lat, lon in ((-85.99, 357.07), (-89.45, 222.69), (-86.0, 0.0)):
        x, y = to_stereo(lat, lon)
        la, lo = from_stereo(x, y)
        assert la == pytest.approx(lat, abs=1e-9) and lo == pytest.approx(lon, abs=1e-9)
    assert to_stereo(-86.0, 0.0)[0] == pytest.approx(0.0, abs=1e-6)


def test_top_spots_respects_separation() -> None:
    xs, ys = np.meshgrid(np.arange(0, 5000, 250.0), np.arange(0, 5000, 250.0))
    h = -np.hypot(xs - 1000, ys - 1000) / 100 + 0.0
    h[0, 19] = 50.0   # isolated spike far away
    h[4, 5] = 9.0     # bump 250 m from the top: must be skipped
    spots = top_spots(xs, ys, h, count=3)
    assert spots[0][2] == 50.0
    assert all(np.hypot(a[0] - b[0], a[1] - b[1]) >= 1000 for i, a in enumerate(spots) for b in spots[i + 1:])
