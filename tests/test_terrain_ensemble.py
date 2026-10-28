"""Terrain-uncertainty ensemble orchestration (no SPICE/DEM needed)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from lunar_core import analysis_service
from lunar_core.api_models import AnalysisRequest
from lunar_core.location_scan import GridOffset
from lunar_core.terrain_ensemble import run_terrain_ensemble
from test_location_scan import BASE_SITE, _fake_result, _Geometry

REQUEST = AnalysisRequest(
    site_ids=[BASE_SITE["site_id"]], horizon_mode="terrain",
    start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-02T00:00:00Z",
)


@pytest.fixture
def stubbed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[float, float, Any]]:
    dem_manifest = tmp_path / "dem.json"
    dem_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(analysis_service, "_load_sites", lambda: {BASE_SITE["site_id"]: BASE_SITE})
    monkeypatch.setattr(analysis_service, "_spice_runtime", lambda: (object(), _Geometry(), "k" * 64, []))
    monkeypatch.setattr(analysis_service, "coverage_preflight", lambda *a: ({}, {}))
    monkeypatch.setattr(analysis_service, "DEM_MANIFEST", dem_manifest)
    monkeypatch.setattr(analysis_service, "PROJECT_ROOT", tmp_path)
    calls: list[tuple[float, float, Any]] = []

    def fake(site: dict[str, Any], request: Any, geometry: Any, *, asset_overrides: Any = None, **_: Any) -> Any:
        calls.append((site["latitude_deg"], site["longitude_deg"], asset_overrides))
        if asset_overrides is None:
            return _fake_result(sunlit=0.0), None
        clone = next(iter(asset_overrides.values()))
        if clone.name == "bad.tif":
            raise analysis_service.TerrainNotReady("override grid mismatch")
        result = _fake_result(sunlit=float(clone.stem.split("-")[1]))
        result["terrain"]["asset_overrides"] = [{"override_sha256": "s" * 64}]
        return result, None

    monkeypatch.setattr(analysis_service, "_run_one_site", fake)
    return calls


def test_ensemble_runs_nominal_then_each_clone_and_summarises(
    tmp_path: Path, stubbed: list[tuple[float, float, Any]],
) -> None:
    clones = [tmp_path / f"c-{v}.tif" for v in (0, 10, 30)] + [tmp_path / "bad.tif"]
    out = run_terrain_ensemble(BASE_SITE["site_id"], REQUEST, asset_id="fine", clone_paths=clones)
    assert stubbed[0][2] is None
    assert [c[2] for c in stubbed[1:]] == [{"fine": p} for p in clones]
    assert {(lat, lon) for lat, lon, _ in stubbed} == {(-89.5, 10.0)}
    s = out["summary"]["sunlit_percent"]
    assert s["nominal"] == 0.0 and s["min"] == 0.0 and s["max"] == 30.0 and s["n"] == 3
    assert s["fraction_of_clones_nonzero"] == pytest.approx(2 / 3)
    assert s["max_abs_change_vs_nominal"] == 30.0
    assert out["members_ok"] == 3 and out["members"][3]["status"] == "unavailable"
    assert out["members"][1]["clone_sha256"] == "s" * 64
    saved = json.loads((tmp_path / "data/ensembles" / f"{out['ensemble_id']}.json").read_text(encoding="utf-8"))
    assert saved["perturbed_asset_id"] == "fine" and len(saved["limits"]) == 4


def test_ensemble_offset_moves_every_member_to_the_same_point(
    tmp_path: Path, stubbed: list[tuple[float, float, Any]],
) -> None:
    run_terrain_ensemble(
        BASE_SITE["site_id"], REQUEST, asset_id="fine", clone_paths=[tmp_path / "c-5.tif"],
        offset=GridOffset(100.0, 0.0), save=False,
    )
    assert len({(lat, lon) for lat, lon, _ in stubbed}) == 1
    assert stubbed[0][:2] != (-89.5, 10.0)


def test_ensemble_rejects_bad_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        run_terrain_ensemble("x", REQUEST, asset_id="a", clone_paths=[])
    with pytest.raises(ValueError, match="duplicate"):
        run_terrain_ensemble("x", REQUEST, asset_id="a", clone_paths=[tmp_path / "a.tif", tmp_path / "a.tif"])
    flat = REQUEST.model_copy(update={"horizon_mode": "flat"})
    with pytest.raises(ValueError, match="terrain"):
        run_terrain_ensemble("x", flat, asset_id="a", clone_paths=[tmp_path / "a.tif"])
