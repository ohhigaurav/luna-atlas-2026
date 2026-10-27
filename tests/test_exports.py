from __future__ import annotations

import csv
import io
import json

from lunar_core.analysis_service import run_as_csv


def sample_payload(kind: str) -> dict:
    site = {
        "site": {"site_id": "reference-test", "name": "Fixture Point"},
        "terrain_status": "flat",
        "series": [{
            "utc": "2027-01-01T00:00:00.000Z", "et_s": 123.0,
            "sun_azimuth_deg": 10.0, "sun_elevation_deg": -1.0, "sun_range_m": 149_000_000_000.0,
            "sun_horizon_deg": -0.1, "sun_margin_deg": -0.9, "sun_visible_upper_limb": False,
            "earth_azimuth_deg": 200.0, "earth_elevation_deg": 0.5, "earth_range_m": 384_400_000.0,
            "earth_horizon_deg": -0.1, "earth_margin_deg": 0.6, "earth_center_clear": True,
        }],
        "sun_windows": [{"start_utc": "2027-01-01T01:00:00.000Z", "end_utc": "2027-01-01T02:00:00.000Z", "start_et_s": 3600.0, "end_et_s": 7200.0, "duration_s": 3600.0, "start_truncated": False, "end_truncated": False}],
        "earth_windows": [], "sun_roots": [], "earth_roots": [],
        "metrics": {"sunlit_fraction": 0.5, "longest_darkness": {"duration_s": 100.0, "truncated_start": True, "truncated_end": False}},
    }
    result = {
        "run_id": "11111111-1111-4111-8111-111111111111", "analysis_kind": kind,
        "validation_status": "computed_not_independently_validated", "created_utc": "2027-01-01T00:00:00Z",
        "settings": {"horizon_mode": "flat"}, "provenance": {"kernel_manifest_sha256": "a" * 64},
        "sites": [site], "site_results": [site], "grid": [],
    }
    if kind == "landing_window_finder":
        result["grid"] = [{
            "site_id": "reference-test", "start_utc": "2027-01-01T00:00:00.000Z",
            "end_utc": "2027-01-15T00:00:00.000Z", "start_et_s": 123.0, "end_et_s": 1_209_723.0,
            "feasible": False, "first_failed_constraint": "max_darkness", "failures": [{"constraint": "max_darkness", "violation": 10.0}],
            "metrics": {"sunlit_fraction": 0.5},
        }]
        result.pop("sites")
    return result


def test_csv_contains_samples_windows_metrics_and_one_consistent_schema() -> None:
    text = run_as_csv(sample_payload("spice_backed_analysis"))
    rows = list(csv.DictReader(io.StringIO(text)))
    assert {row["record_type"] for row in rows} >= {"run_manifest", "sample", "window", "metric"}
    assert all(len(row) == len(rows[0]) for row in rows)
    manifest = next(row for row in rows if row["record_type"] == "run_manifest")
    assert json.loads(manifest["provenance_json"])["kernel_manifest_sha256"] == "a" * 64
    assert any(row["target"] == "SUN" for row in rows if row["record_type"] == "sample")
    assert any(row["target"] == "EARTH" for row in rows if row["record_type"] == "sample")
    assert any(row["window_type"] == "SUN" for row in rows if row["record_type"] == "window")


def test_finder_csv_includes_constraint_grid_rows() -> None:
    text = run_as_csv(sample_payload("landing_window_finder"))
    rows = list(csv.DictReader(io.StringIO(text)))
    finder = [row for row in rows if row["record_type"] == "finder_cell"]
    assert len(finder) == 1
    assert finder[0]["feasible"] == "False"
    assert finder[0]["first_failed_constraint"] == "max_darkness"
    assert json.loads(finder[0]["failures_json"])[0]["constraint"] == "max_darkness"
    assert all(len(row) == len(rows[0]) for row in rows)
