"""One-button check: defaults, cache, terrain fallback and the plain summary (synthetic geometry)."""
from __future__ import annotations

from typing import Any

import pytest
from lunar_core import analysis_service, check
from lunar_core.api_models import CheckRequest, MissionConstraints
from pydantic import ValidationError

from tests.test_analysis_service_integration import (  # noqa: F401
    TEST_SITE,
    synthetic_service_environment,
)


def _req(**kw: Any) -> CheckRequest:
    return CheckRequest(**{"site_id": TEST_SITE["site_id"], "start_utc": "2027-01-01T00:00:00Z", "days": 1, **kw})


@pytest.fixture
def no_terrain(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record requested modes; terrain always unavailable (as for a point without DEM coverage)."""
    modes: list[str] = []
    real = analysis_service._build_site_horizon

    def fake(site: Any, geometry: Any, request: Any, overrides: Any = None) -> Any:
        modes.append(request.horizon_mode)
        if request.horizon_mode == "terrain":
            raise analysis_service.TerrainNotReady("no DEM here (test)")
        return real(site, geometry, request, overrides)

    monkeypatch.setattr(analysis_service, "_build_site_horizon", fake)
    return modes


def test_human_duration() -> None:
    assert check.human_duration(0) == "0 min"
    assert check.human_duration(59 * 60 + 59) == "59 min"
    assert check.human_duration(5 * 3600 + 20 * 60) == "5 h 20 min"
    assert check.human_duration(3 * 86400 + 4 * 3600 + 59 * 60) == "3 d 4 h"


def test_request_limits() -> None:
    assert _req().panel_height_m == 2.0
    for bad in ({"days": 0}, {"days": 61}, {"panel_height_m": 10.5}, {"start_utc": "2027-01-01T00:00:00"},
                {"horizon_mode": "flat"}):
        with pytest.raises(ValidationError):
            _req(**bad)


@pytest.mark.usefixtures("synthetic_service_environment")
def test_polar_site_falls_back_to_flat_with_a_visible_note_then_hits_cache(no_terrain: list[str]) -> None:
    first = check.run_check(_req(panel_height_m=0.0))
    assert no_terrain == ["terrain", "flat"]
    assert first["cache_hit"] is False
    assert first["chosen_settings"]["horizon_mode"] == "flat"
    assert first["chosen_settings"]["sun_observer_height_m"] == 0.0
    assert first["chosen_settings"]["event_tolerance_s"] == 10.0
    caveats = " ".join(first["summary"]["caveats"])
    assert "Terrain was not available" in caveats and "Flat horizon" in caveats
    second = check.run_check(_req(panel_height_m=0.0))
    assert second["cache_hit"] is True and second["run_id"] == first["run_id"]
    assert no_terrain == ["terrain", "flat"]  # nothing recomputed
    assert "Terrain was not available" in " ".join(second["summary"]["caveats"])
    other = check.run_check(_req(panel_height_m=5.0))
    assert other["cache_hit"] is False and other["run_id"] != first["run_id"]


@pytest.mark.usefixtures("synthetic_service_environment")
def test_unknown_site_is_a_validation_error(no_terrain: list[str]) -> None:
    with pytest.raises(ValueError, match="unknown site"):
        check.run_check(_req(site_id="nope"))


@pytest.mark.usefixtures("synthetic_service_environment")
def test_stale_cache_entry_is_recomputed(no_terrain: list[str]) -> None:
    first = check.run_check(_req())
    (analysis_service.RUNS_DIR / f"{first['run_id']}.json").unlink()
    again = check.run_check(_req())
    assert again["cache_hit"] is False and again["run_id"] != first["run_id"]


def _run(sun: float, earth: float, dark_s: float, dark_trunc: bool = False) -> dict[str, Any]:
    outage = {"duration_s": dark_s, "truncated_start": dark_trunc, "truncated_end": False}
    return {"sites": [{
        "site": {"site_id": "s", "origin": "reference"}, "terrain_status": "terrain-verified",
        "metrics": {"sunlit_percent": sun, "dte_clear_percent": earth, "both_percent": min(sun, earth),
                    "longest_darkness": outage, "longest_dte_gap": {"duration_s": 3600.0},
                    "longest_joint_outage": {"duration_s": 1800.0}, "sun_window_count": 1},
        "sun_windows": [{"start_utc": "a", "end_utc": "b"}], "earth_windows": [],
    }]}


def test_summary_text_and_limits() -> None:
    s = check.summarise(_run(61.2, 0.0, 60 * 3600), height_m=2, horizon_note=None, constraints=MissionConstraints())
    assert s["headline"].startswith("Some of the Sun is visible from a panel 2 m above the ground 61% of the time")
    assert any("Earth never rises" in line for line in s["lines"])
    status = {c["key"]: c["status"] for c in s["limits"]["checks"]}
    assert status == {"darkness": "fail", "earth_gap": "pass", "joint_outage": "pass", "sunlit": "pass"}
    assert s["limits"]["all_pass"] is False
    assert "Reference site" in s["caveats"][0]


def test_summary_truncated_outage_is_a_lower_bound_and_not_a_pass() -> None:
    s = check.summarise(_run(80, 50, 10 * 3600, dark_trunc=True), height_m=0, horizon_note=None,
                        constraints=MissionConstraints())
    dark = next(c for c in s["limits"]["checks"] if c["key"] == "darkness")
    assert dark["status"] == "unknown" and dark["text"].startswith("at least")


def test_summary_special_cases() -> None:
    never = check.summarise(_run(0.0, 100.0, 86400), height_m=0, horizon_note=None, constraints=MissionConstraints())
    assert any("never clears the horizon" in line for line in never["lines"])
    assert any("stays in view" in line for line in never["lines"])
    always = check.summarise(_run(100.0, 40.0, 0.0), height_m=10, horizon_note=None, constraints=MissionConstraints())
    assert any("never sets" in line for line in always["lines"])


@pytest.mark.usefixtures("synthetic_service_environment")
def test_http_check(no_terrain: list[str]) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from lunar_core.api import app

    client = TestClient(app)
    ok = client.post("/api/check", json={"site_id": TEST_SITE["site_id"], "start_utc": "2027-01-01T00:00:00Z", "days": 1})
    assert ok.status_code == 200 and ok.json()["kind"] == "site_check"
    assert client.post("/api/check", json={"site_id": "x", "start_utc": "2027-01-01T00:00:00Z", "days": 99}).status_code == 422
    assert client.post("/api/check", json={"site_id": "nope", "start_utc": "2027-01-01T00:00:00Z"}).status_code == 422


def test_disc_fraction_and_mean() -> None:
    from lunar_core.check import disc_visible_fraction, sun_disc_percent

    assert disc_visible_fraction(0.0, 0.27) == pytest.approx(0.5)
    assert disc_visible_fraction(0.27, 0.27) == 1.0 and disc_visible_fraction(-0.3, 0.27) == 0.0
    assert disc_visible_fraction(0.135, 0.27) == pytest.approx(0.8045, abs=1e-3)   # h = 0.5
    au = 149_597_870_700.0
    rows = [{"sun_range_m": au, "sun_horizon_deg": 1.0, "sun_elevation_deg": e} for e in (2.0, 1.0, 0.0)]
    assert sun_disc_percent(rows) == pytest.approx(100 * (1.0 + 0.5 + 0.0) / 3)
    assert sun_disc_percent([{"sun_range_m": None, "sun_horizon_deg": 0.0, "sun_elevation_deg": 1.0}]) is None
