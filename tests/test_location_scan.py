"""Location-sensitivity scan: grid geometry, statistics and orchestration (no SPICE/DEM needed)."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from lunar_core import analysis_service
from lunar_core.api_models import AnalysisRequest
from lunar_core.location_scan import (
    GridOffset,
    centre_rank,
    offset_point,
    run_location_scan,
    scan_offsets,
    summarise,
)

RADIUS = 1_737_400.0


def test_default_grid_is_29_points_centre_first_inside_disc() -> None:
    offsets = scan_offsets(300.0, 100.0)
    assert len(offsets) == 29
    assert offsets[0] == GridOffset(0.0, 0.0)
    assert all(o.distance_m <= 300.0 + 1e-3 for o in offsets)
    assert len({(o.east_m, o.north_m) for o in offsets}) == 29
    assert GridOffset(300.0, 0.0) in offsets and GridOffset(200.0, 300.0) not in offsets


def test_grid_rejects_bad_parameters_and_huge_scans() -> None:
    assert scan_offsets(0.0, 50.0) == [GridOffset(0.0, 0.0)]
    with pytest.raises(ValueError):
        scan_offsets(300.0, 0.0)
    with pytest.raises(ValueError):
        scan_offsets(float("nan"), 10.0)
    with pytest.raises(ValueError, match="cap"):
        scan_offsets(1_000.0, 10.0)


def test_offset_bearings() -> None:
    assert GridOffset(0.0, 100.0).azimuth_deg == pytest.approx(0.0)
    assert GridOffset(100.0, 0.0).azimuth_deg == pytest.approx(90.0)
    assert GridOffset(0.0, -100.0).azimuth_deg == pytest.approx(180.0)
    assert GridOffset(-100.0, 0.0).azimuth_deg == pytest.approx(270.0)


def _surface_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return RADIUS * math.acos(max(-1.0, min(1.0, c)))


@pytest.mark.parametrize("east,north", [(300.0, 0.0), (0.0, -300.0), (-200.0, 200.0), (100.0, 100.0)])
def test_offset_point_lands_at_requested_distance_near_the_pole(east: float, north: float) -> None:
    lat0, lon0 = -89.78, 222.69  # near-polar: the azimuth frame turns quickly with position
    lat, lon = offset_point(lat0, lon0, GridOffset(east, north), RADIUS)
    assert _surface_distance(lat0, lon0, lat, lon) == pytest.approx(math.hypot(east, north), abs=1e-3)


def test_offset_point_north_moves_away_from_south_pole_and_centre_is_unchanged() -> None:
    lat, _lon = offset_point(-89.5, 10.0, GridOffset(0.0, 100.0), RADIUS)
    assert lat == pytest.approx(-89.5 + math.degrees(100.0 / RADIUS), abs=1e-9)
    assert offset_point(-89.5, 10.0, GridOffset(0.0, 0.0), RADIUS) == (-89.5, 10.0)


def test_summary_statistics_and_rank() -> None:
    s = summarise([0.0, 10.0, 20.0, 30.0, 40.0, float("nan")])
    assert s == {"n": 5, "min": 0.0, "p25": 10.0, "median": 20.0, "p75": 30.0, "max": 40.0}
    assert summarise([])["n"] == 0
    assert summarise([7.0])["p25"] == 7.0
    assert centre_rank([0.0, 10.0, 20.0, 30.0], 0.0) == 0.0
    assert centre_rank([0.0, 10.0, 20.0, 30.0], 25.0) == 0.75
    assert centre_rank([], 1.0) is None


BASE_SITE = {
    "site_id": "synthetic-scan-site", "name": "Synthetic Scan Site", "latitude_deg": -89.5,
    "longitude_deg": 10.0, "latitude_type": "planetocentric", "catalogue_kind": "test_fixture",
    "source_url": "https://example.invalid", "source_record": "fixture",
}


class _Geometry:
    reference_radius_m = RADIUS
    frame = "TEST"
    aberration_correction = "NONE"

    def utc_to_et(self, utc: str) -> float:
        return 0.0 if utc.startswith("2027-01-01") else 86_400.0


def _fake_result(sunlit: float) -> dict[str, Any]:
    span = {"duration_s": 7200.0, "display_prefix": ""}
    return {
        "metrics": {"sunlit_percent": sunlit, "dte_clear_percent": 50.0, "both_percent": sunlit / 2,
                    "longest_darkness": span, "longest_dte_gap": span},
        "event_precision": {"discovery_certified": True, "sun_possible_grazing": [], "earth_possible_grazing": []},
        "horizon_profile": [{"elevation_deg": 1.0}, {"elevation_deg": 2.5}],
        "terrain": {"site_ground_elevation_m": 1700.0, "cache_hit": False},
    }


def test_scan_runs_each_point_through_the_site_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dem_manifest = tmp_path / "dem.json"
    dem_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(analysis_service, "_load_sites", lambda: {BASE_SITE["site_id"]: BASE_SITE})
    monkeypatch.setattr(analysis_service, "_spice_runtime", lambda: (object(), _Geometry(), "k" * 64, []))
    monkeypatch.setattr(analysis_service, "assert_required_spk_coverage", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(analysis_service, "assert_required_bpc_coverage", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(analysis_service, "DEM_MANIFEST", dem_manifest)
    monkeypatch.setattr(analysis_service, "PROJECT_ROOT", tmp_path)

    seen: list[tuple[str, float, float]] = []

    def fake_run_one_site(site: dict[str, Any], request: Any, geometry: Any, **_: Any) -> tuple[dict[str, Any], None]:
        seen.append((site["site_id"], site["latitude_deg"], site["longitude_deg"]))
        if len(seen) == 5:
            raise analysis_service.TerrainNotReady("synthetic coverage gap")
        return _fake_result(sunlit=0.0 if len(seen) == 1 else 80.0), None

    monkeypatch.setattr(analysis_service, "_run_one_site", fake_run_one_site)
    request = AnalysisRequest(
        site_ids=[BASE_SITE["site_id"]], horizon_mode="terrain",
        start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-02T00:00:00Z",
    )
    scan = run_location_scan(BASE_SITE["site_id"], request, radius_m=200.0, spacing_m=100.0)

    assert len(seen) == 13 and scan["grid"]["point_count"] == 13
    assert {site_id for site_id, _lat, _lon in seen} == {BASE_SITE["site_id"]}  # same DEM selection
    assert seen[0][1:] == (-89.5, 10.0)                                          # centre first, unmoved
    assert len({(lat, lon) for _s, lat, lon in seen}) == 13                      # every point distinct
    assert scan["points_ok"] == 12 and scan["points_unavailable"] == 1
    assert scan["points"][4]["status"] == "unavailable" and "coverage gap" in scan["points"][4]["error"]
    sunlit = scan["summary"]["sunlit_percent"]
    assert sunlit["min"] == 0.0 and sunlit["max"] == 80.0 and sunlit["n"] == 12
    assert sunlit["centre"] == 0.0 and sunlit["fraction_of_points_below_centre"] == 0.0
    assert scan["all_certified"] is True
    saved = json.loads((tmp_path / "data" / "scans" / f"{scan['scan_id']}.json").read_text(encoding="utf-8"))
    assert saved["points"][0]["horizon_max_deg"] == 2.5


def test_scan_refuses_flat_mode() -> None:
    request = AnalysisRequest(
        site_ids=["x"], horizon_mode="flat",
        start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-02T00:00:00Z",
    )
    with pytest.raises(ValueError, match="terrain"):
        run_location_scan("x", request)


def _scan_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AnalysisRequest:
    dem_manifest = tmp_path / "dem.json"
    dem_manifest.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(analysis_service, "_load_sites", lambda: {BASE_SITE["site_id"]: BASE_SITE})
    monkeypatch.setattr(analysis_service, "_spice_runtime", lambda: (object(), _Geometry(), "k" * 64, []))
    monkeypatch.setattr(analysis_service, "assert_required_spk_coverage", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(analysis_service, "assert_required_bpc_coverage", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(analysis_service, "DEM_MANIFEST", dem_manifest)
    monkeypatch.setattr(analysis_service, "PROJECT_ROOT", tmp_path)
    return AnalysisRequest(site_ids=[BASE_SITE["site_id"]], horizon_mode="terrain",
                           start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-02T00:00:00Z")


def test_scan_lets_other_requests_in_between_points(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time as _time
    request = _scan_env(tmp_path, monkeypatch)
    events: list[str] = []
    first_point = threading.Event()

    def fake_run_one_site(site: dict[str, Any], request: Any, geometry: Any, **_: Any) -> tuple[dict[str, Any], None]:
        assert analysis_service._RUN_LOCK.locked()       # each point still runs under the lock
        events.append("point")
        first_point.set()
        _time.sleep(0.01)
        return _fake_result(sunlit=50.0), None

    def other_user() -> None:
        first_point.wait(2)
        with analysis_service._RUN_LOCK:                 # e.g. another judge's landing question
            events.append("other")

    monkeypatch.setattr(analysis_service, "_run_one_site", fake_run_one_site)
    t = threading.Thread(target=other_user)
    t.start()
    scan = run_location_scan(BASE_SITE["site_id"], request, radius_m=200.0, spacing_m=100.0, save=False)
    t.join(2)
    assert scan["points_ok"] == 13 and events.count("point") == 13
    assert "other" in events and events.index("other") < len(events) - 1   # got in before the scan finished


def test_scan_stops_if_the_kernel_pool_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    request = _scan_env(tmp_path, monkeypatch)
    monkeypatch.setattr(analysis_service, "_LOADED_KERNELS", (("manifest-a", ()), None))
    calls = []

    def fake_run_one_site(site: dict[str, Any], request: Any, geometry: Any, **_: Any) -> tuple[dict[str, Any], None]:
        calls.append(1)
        if len(calls) == 2:   # someone reloaded kernels from another manifest between points
            analysis_service._LOADED_KERNELS = (("manifest-b", ()), None)
        return _fake_result(sunlit=50.0), None

    monkeypatch.setattr(analysis_service, "_run_one_site", fake_run_one_site)
    with pytest.raises(analysis_service.AnalysisNotReady, match="kernel pool changed"):
        run_location_scan(BASE_SITE["site_id"], request, radius_m=200.0, spacing_m=100.0, save=False)
    assert len(calls) == 2
