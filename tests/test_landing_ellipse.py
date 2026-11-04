"""Landing-ellipse risk: grid geometry, risk summary, caching and site rules (no kernels/DEMs)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from lunar_core import analysis_service, landing_ellipse, location_scan
from lunar_core.api_models import AnalysisRequest, EllipseRequest
from pydantic import ValidationError


def test_circle_grid_counts_and_centre_first() -> None:
    pts = landing_ellipse.ellipse_offsets(100, 100, 0, 50)
    assert len(pts) == 13 and pts[0].distance_m == 0.0
    assert all(p.distance_m <= 100 + 1e-6 for p in pts)


def test_orientation_is_bearing_of_major_axis() -> None:
    east = {(p.east_m, p.north_m) for p in landing_ellipse.ellipse_offsets(200, 50, 90, 50)}
    assert (150.0, 0.0) in east and (0.0, 150.0) not in east
    north = {(p.east_m, p.north_m) for p in landing_ellipse.ellipse_offsets(200, 50, 0, 50)}
    assert (0.0, 150.0) in north and (150.0, 0.0) not in north
    with pytest.raises(ValueError):
        landing_ellipse.ellipse_offsets(50, 100, 0, 10)


def test_auto_spacing_targets_about_45_points_with_a_floor() -> None:
    s = landing_ellipse.auto_spacing(250, 250)
    assert 30 <= len(landing_ellipse.ellipse_offsets(250, 250, 0, s)) <= 60
    assert landing_ellipse.auto_spacing(30, 30) == landing_ellipse.MIN_SPACING_M


def _pt(e: float, n: float, sun: float, earth: float = 50.0, status: str = "ok") -> dict[str, Any]:
    return {"east_m": e, "north_m": n, "distance_m": (e * e + n * n) ** 0.5, "latitude_deg": -89.0,
            "longitude_deg": 10.0, "status": status, "sunlit_percent": sun, "dte_clear_percent": earth,
            "both_percent": min(sun, earth)}


def test_risk_summary() -> None:
    pts = [_pt(0, 0, 0.0), _pt(100, 0, 98.0), _pt(0, 100, 60.0), _pt(-100, 0, 5.0), _pt(0, -100, 70.0),
           _pt(50, 50, 0.0, status="unavailable")]
    r = landing_ellipse.risk_summary(pts)
    assert r["points_ok"] == 5
    assert r["sunlit_percent"]["worst"] == 0.0 and r["sunlit_percent"]["best"] == 98.0
    assert r["sunlit_percent"]["median"] == 60.0
    assert r["dark_trap_share"] == pytest.approx(2 / 5)
    assert r["target"]["sunlit_percent"] == 0.0 and r["best_point"]["east_m"] == 100.0
    assert r["chips"][0] == "best 98% ☀" and r["chips"][-1].startswith("40% of ellipse")
    assert landing_ellipse.risk_summary([_pt(0, 0, 1, status="unavailable")]) == {"points_ok": 0}


def test_request_rules() -> None:
    ok = EllipseRequest(site_id="s", start_utc="2027-01-01T00:00:00Z")
    assert (ok.semi_major_m, ok.days, ok.semi_minor_m) == (250.0, 14, None)
    for bad in ({"semi_major_m": 2000}, {"semi_minor_m": 300}, {"orientation_deg": 180}, {"days": 31},
                {"start_utc": "2027-01-01T00:00:00"}):
        with pytest.raises(ValidationError):
            EllipseRequest(**{"site_id": "s", "start_utc": "2027-01-01T00:00:00Z", **bad})


@pytest.fixture
def fake_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    sites = {"polar": {"site_id": "polar", "latitude_deg": -89.5, "longitude_deg": 10.0},
             "equator": {"site_id": "equator", "latitude_deg": 0.5, "longitude_deg": 20.0}}
    monkeypatch.setattr(analysis_service, "_load_sites", lambda: sites)
    monkeypatch.setattr(analysis_service, "RUNS_DIR", tmp_path / "runs")

    def scan(site_id: str, request: AnalysisRequest, **kw: Any) -> dict[str, Any]:
        calls.append({"site_id": site_id, "request": request, **kw})
        pts = [_pt(o.east_m, o.north_m, 80.0 if o.distance_m else 0.0) for o in kw["offsets"]]
        return {"site": {"site_id": site_id}, "settings": {"horizon_mode": request.horizon_mode},
                "points": pts, "points_unavailable": 0, "provenance": {"fake": True}}

    monkeypatch.setattr(location_scan, "run_location_scan", scan)
    return calls


def test_ellipse_run_uses_terrain_caches_and_rejects_non_polar(fake_scan: list[dict[str, Any]]) -> None:
    req = EllipseRequest(site_id="polar", start_utc="2027-01-01T00:00:00Z", semi_major_m=200, days=3)
    first = landing_ellipse.run_landing_ellipse(req)
    assert first["cache_hit"] is False and first["kind"] == "landing_ellipse"
    assert fake_scan[0]["request"].horizon_mode == "terrain" and fake_scan[0]["save"] is False
    assert first["risk"]["target"]["sunlit_percent"] == 0.0 and first["risk"]["sunlit_percent"]["best"] == 80.0
    assert first["ellipse"]["point_count"] == len(fake_scan[0]["offsets"])
    second = landing_ellipse.run_landing_ellipse(req)
    assert second["cache_hit"] is True and len(fake_scan) == 1
    with pytest.raises(ValueError, match="60 S"):
        landing_ellipse.run_landing_ellipse(req.model_copy(update={"site_id": "equator"}))
    with pytest.raises(ValueError, match="unknown site"):
        landing_ellipse.run_landing_ellipse(req.model_copy(update={"site_id": "nope"}))


def test_location_scan_rejects_empty_offsets() -> None:
    req = AnalysisRequest(site_ids=["x"], start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-02T00:00:00Z",
                          horizon_mode="terrain")
    with pytest.raises(ValueError, match="offsets"):
        location_scan.run_location_scan("x", req, offsets=[])
