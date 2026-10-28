"""Pure parts of the DEM review tool (Rasterio/pyproj parts run on real files locally)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tools import review_dem


def test_hand_projection_reproduces_values_printed_by_pyproj_for_site_001() -> None:
    # bootstrap.log on the project laptop (pyproj, Product 78 Site01 CRS) mapped
    # reference-lola-site-001 (89.45 S, 222.69 E) to x=-11308.187770988527, y=-12258.857997599198.
    x, y = review_dem.stereographic_south(-89.45, 222.69, 1_737_400.0)
    assert float(x) == pytest.approx(-11308.187770988527, abs=1e-3)
    assert float(y) == pytest.approx(-12258.857997599198, abs=1e-3)


def test_hand_projection_round_trips() -> None:
    lat = np.array([-89.9, -88.0, -85.5, -61.0])
    lon = np.array([0.0, 129.4, -150.0, 357.07])
    x, y = review_dem.stereographic_south(lat, lon, 1_737_400.0)
    back_lat, back_lon = review_dem.stereographic_south_inverse(x, y, 1_737_400.0)
    np.testing.assert_allclose(back_lat, lat, atol=1e-10)
    np.testing.assert_allclose((back_lon - lon + 180.0) % 360.0 - 180.0, 0.0, atol=1e-10)


def test_summarise_ignores_unknown_values() -> None:
    stats = review_dem.summarise([1.0, np.nan, 3.0, 2.0])
    assert stats["count"] == 3 and stats["median"] == 2.0 and stats["min"] == 1.0


def _write(tmp_path: Path, passed: bool) -> tuple[Path, Path, dict]:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"assets": [{"asset_id": "fine"}, {"asset_id": "regional"}]}), encoding="utf-8")
    report = {
        "created_utc": "2026-10-28T09:00:00Z", "body_radius_m": 1737400.0, "passed": passed,
        "assets": [
            {"asset_id": "fine", "max_projection_error_vs_hand_formula_m": 1e-6, "max_roundtrip_error_deg": 1e-12,
             "pixel_size_m": [5.0, 5.0], "height_stats_m": {"min": 1000.0, "max": 2500.0},
             "difference_vs_regional_m": {"regional_asset": "regional", "median": 0.4, "count": 1600, "p05": -9.0, "p95": 8.0}},
            {"asset_id": "regional", "max_projection_error_vs_hand_formula_m": 1e-6, "max_roundtrip_error_deg": 1e-12,
             "pixel_size_m": [240.0, 240.0], "height_stats_m": {"min": -4000.0, "max": 6000.0}},
        ],
    }
    report_path = review_dem.ROOT / "validation" / "evidence" / "_test_dem_review.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return manifest, report_path, report


def test_attest_sets_flags_with_evidence_notes(tmp_path: Path) -> None:
    manifest, report_path, report = _write(tmp_path, passed=True)
    try:
        review_dem.attest(manifest, report_path, report, "The team")
        assets = json.loads(manifest.read_text())["assets"]
        assert all(a["crs_contract_verified"] and a["vertical_datum_verified"] for a in assets)
        assert "The team" in assets[0]["crs_verification_note"]
        assert "Median difference to regional 0.40 m" in assets[0]["vertical_datum_verification_note"]
        assert "Inferred, not stated by the publisher" in assets[1]["vertical_datum_verification_note"]
    finally:
        report_path.unlink()


def test_attest_refuses_when_any_check_failed(tmp_path: Path) -> None:
    manifest, report_path, report = _write(tmp_path, passed=False)
    try:
        with pytest.raises(SystemExit, match="refusing"):
            review_dem.attest(manifest, report_path, report, "The team")
        assert "crs_contract_verified" not in json.loads(manifest.read_text())["assets"][0]
    finally:
        report_path.unlink()
