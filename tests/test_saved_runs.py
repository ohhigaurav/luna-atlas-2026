from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_core import analysis_service

VALID_ID = "11111111-1111-4111-8111-111111111111"


def _write_run(directory: Path, run_id: str = VALID_ID, *, created: str = "2027-01-01T00:00:00Z") -> None:
    payload = {
        "run_id": run_id,
        "analysis_kind": "spice_backed_analysis",
        "validation_status": "computed_not_independently_validated",
        "created_utc": created,
        "settings": {"start_utc": "2027-01-01T00:00:00Z", "end_utc": "2027-01-02T00:00:00Z"},
        "sites": [{"site": {"site_id": "reference-test", "name": "Test Reference Site"}}],
        "provenance": {"software_version": "test"},
    }
    (directory / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_saved_run_listing_returns_small_summaries_and_skips_invalid_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path)
    _write_run(tmp_path)
    (tmp_path / "not-a-uuid.json").write_text("{}", encoding="utf-8")
    mismatch_id = "22222222-2222-4222-8222-222222222222"
    _write_run(tmp_path, mismatch_id)
    mismatch_path = tmp_path / f"{mismatch_id}.json"
    mismatch_payload = json.loads(mismatch_path.read_text(encoding="utf-8"))
    mismatch_payload["run_id"] = VALID_ID
    mismatch_path.write_text(json.dumps(mismatch_payload), encoding="utf-8")

    result = analysis_service.list_saved_runs(limit=10)

    assert result["total"] == 1
    assert result["invalid_run_files_ignored"] == 2
    summary = result["runs"][0]
    assert summary["run_id"] == VALID_ID
    assert summary["site_names"] == ["Test Reference Site"]
    assert summary["start_utc"] == "2027-01-01T00:00:00Z"
    assert "sites" not in summary  # The index must not return long time series.


def test_saved_run_listing_sorts_newest_first_and_obeys_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path)
    ids = [
        "11111111-1111-4111-8111-111111111111",
        "22222222-2222-4222-8222-222222222222",
    ]
    _write_run(tmp_path, ids[0], created="2027-01-01T00:00:00Z")
    _write_run(tmp_path, ids[1], created="2027-01-02T00:00:00Z")

    result = analysis_service.list_saved_runs(limit=1)

    assert result["total"] == 2
    assert len(result["runs"]) == 1
    assert result["runs"][0]["run_id"] == ids[1]


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_saved_run_listing_rejects_invalid_limits(limit: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        analysis_service.list_saved_runs(limit=limit)


def test_load_saved_run_rejects_manifest_id_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path)
    _write_run(tmp_path, VALID_ID)
    path = tmp_path / f"{VALID_ID}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["run_id"] = "22222222-2222-4222-8222-222222222222"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid or mismatched manifest"):
        analysis_service.load_saved_run(VALID_ID)


def test_load_saved_run_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="invalid run_id"):
        analysis_service.load_saved_run("../outside")
