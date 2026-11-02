from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import wac_manypoint_diagnostics as diag


def test_least_squares_recovers_line() -> None:
    a, b = diag.least_squares([0, 10, 20, 30], [1, 6, 11, 16])
    assert a == pytest.approx(1.0) and b == pytest.approx(0.5)
    with pytest.raises(ValueError):
        diag.least_squares([1, 1], [1, 2])


def test_describe_and_relief(tmp_path: Path) -> None:
    ckpt = tmp_path / "c.jsonl"
    ckpt.write_text("\n".join(json.dumps({"site_id": "s", "row": r, "col": 0, "ground_m": g})
                              for r in range(5) for g in (0.0, float(r))), encoding="utf-8")
    relief = diag.relief_by_pixel(ckpt)
    assert relief[("s", 3, 0)] == 3.0
    pixels = [{"site_id": "s", "row": r, "col": 0, "stratum": min(r, 4), "wac_pct": 10.0 * r + 1,
               "model_limb_pct": 5.0 * r, "model_centre_pct": 4.0 * r,
               "model_point_min_pct": 4.0 * r, "model_point_max_pct": 6.0 * r} for r in range(5)]
    text = "\n".join(diag.describe(pixels, relief))
    assert "fit: model_limb" in text and "sub-pixel ground relief" in text
