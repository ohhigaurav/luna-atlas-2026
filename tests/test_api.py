from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from lunar_core.api import app

client = TestClient(app)

# Every test here describes the behaviour of an unconfigured checkout, independent of whatever
# kernels, DEMs, official sites or saved runs exist in the developer's real data/ folder.
pytestmark = pytest.mark.usefixtures("unconfigured_project")


def test_health_explicitly_reports_not_ready() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "configuration_required"
    assert payload["science_core_ready"] is False
    assert payload["official_site_count"] == 0
    assert payload["kernel_manifest_state"] == "not_configured"
    assert payload["kernel_preflight_ready"] is False
    assert len(payload["kernel_manifest_sha256"]) == 64
    assert payload["kernel_preflight_issues"]


def test_sites_never_advertises_test_fixtures() -> None:
    response = client.get("/api/sites")
    assert response.status_code == 200
    payload = response.json()
    assert payload["catalogue_state"] == "awaiting_official_source"
    assert payload["site_count"] == 0
    assert payload["sites"] == []


def test_root_serves_the_four_screen_local_app_and_security_headers() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Compare" in response.text
    assert "Landing-window finder" in response.text
    assert "Assumptions & sources" in response.text
    assert "Export & provenance" in response.text
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]


def test_source_and_assumption_endpoints_are_machine_readable() -> None:
    source_response = client.get("/api/sources")
    assumption_response = client.get("/api/assumptions")
    assert source_response.status_code == 200
    assert assumption_response.status_code == 200
    names = {item["name"] for item in source_response.json()["sources"]}
    assert "NASA PGDA Product 78" in names
    assert "JPL Horizons API documentation" in names
    assert "not communication availability" in assumption_response.json()["earth_visibility"]


def test_analysis_is_fail_closed_without_real_geometry_configuration() -> None:
    response = client.post("/api/analysis", json={
        "site_ids": ["reference-malapert-massif"],
        "start_utc": "2027-01-01T00:00:00Z",
        "end_utc": "2027-01-02T00:00:00Z",
        "horizon_mode": "flat",
    })
    assert response.status_code == 503
    assert "spiceypy" in response.json()["detail"].lower() or "kernel" in response.json()["detail"].lower()


def test_request_rejects_non_utc_offsets_before_analysis() -> None:
    response = client.post("/api/analysis", json={
        "site_ids": ["reference-malapert-massif"],
        "start_utc": "2027-01-01T01:00:00+01:00",
        "end_utc": "2027-01-02T00:00:00Z",
        "horizon_mode": "flat",
    })
    assert response.status_code == 422


def test_local_static_bundle_is_served_without_third_party_runtime_assets() -> None:
    css = client.get("/static/app.css")
    js = client.get("/static/app.js")
    openapi = client.get("/api/openapi.json")
    assert css.status_code == 200 and len(css.text) > 1000
    assert js.status_code == 200 and "SIMULATED INTERFACE DATA ONLY" in js.text
    assert openapi.status_code == 200
    assert "https://cdn." not in js.text


def test_terrain_coverage_endpoint_is_live_and_explicit_when_no_dem_is_registered() -> None:
    response = client.get("/api/terrain-coverage")
    assert response.status_code == 200
    payload = response.json()
    assert payload["manifest_state"] == "not_configured"
    assert payload["asset_count"] == 0
    assert payload["assets"] == []
    assert any("No DEM assets" in item for item in payload["issues"])


def test_saved_run_index_is_available_even_before_any_run_exists() -> None:
    response = client.get("/api/runs")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["runs"], list)
    assert payload["total"] >= len(payload["runs"])
    assert "invalid_run_files_ignored" in payload


def test_finder_is_fail_closed_without_real_geometry_configuration() -> None:
    response = client.post("/api/finder", json={
        "site_ids": ["reference-malapert-massif"],
        "search_start_utc": "2027-01-01T00:00:00Z",
        "search_end_utc": "2027-01-02T00:00:00Z",
        "mission_duration_days": 7,
        "horizon_mode": "flat",
    })
    assert response.status_code == 503
    assert "spiceypy" in response.json()["detail"].lower() or "kernel" in response.json()["detail"].lower()


def test_root_serves_built_app_when_present_and_legacy_stays_reachable(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from lunar_core import api

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Luna Atlas 3D</title>", encoding="utf-8")
    monkeypatch.setattr(api, "FRONTEND_APP_DIST", dist)
    assert "Luna Atlas 3D" in client.get("/").text
    legacy = client.get("/legacy")
    assert legacy.status_code == 200 and "Landing-window finder" in legacy.text
    assert "worker-src 'self' blob:" in legacy.headers["content-security-policy"]
