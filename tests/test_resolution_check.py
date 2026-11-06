"""Pure helpers of tools/resolution_check.py (the 5 m vs 240 m runs need real DEMs)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.resolution_check import quantile, summarise_pairs  # noqa: E402


def test_quantile() -> None:
    assert quantile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == 3.0
    assert quantile([0.0, 10.0], 0.9) == pytest.approx(9.0)
    assert quantile([7.0], 0.9) == 7.0


def test_summarise_pairs() -> None:
    pairs = [{"sun_tile": 69.0, "sun_regional": 100.0, "earth_tile": 36.0, "earth_regional": 53.0},
             {"sun_tile": 0.0, "sun_regional": 0.0, "earth_tile": 0.0, "earth_regional": 0.0},
             {"sun_tile": 50.0, "sun_regional": 45.0, "earth_tile": 40.0, "earth_regional": 40.0}]
    s = summarise_pairs(pairs)
    assert s["n"] == 3 and s["sun_signed_median"] == 0.0 and s["sun_abs_median"] == 5.0
    assert s["sun_share_over_10"] == pytest.approx(1 / 3)
    assert (s["sun_regional_higher"], s["sun_regional_lower"]) == (1, 1)
    assert s["earth_abs_median"] == 0.0
