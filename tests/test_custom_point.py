"""Landing windows and checks for a point the user picked (lunar_core.custom_point)."""
from __future__ import annotations

from typing import Any

import pytest
from lunar_core import analysis_service, check, custom_point, landing
from lunar_core.api_models import AnalysisRequest, CheckRequest, LandingRequest
from pydantic import ValidationError

from tests.test_analysis_service_integration import (  # noqa: F401
    TEST_SITE,
    synthetic_service_environment,
)


def test_normalise_and_label() -> None:
    assert custom_point.normalise(-89.45, -137.31) == (-89.45, 222.69)
    assert custom_point.normalise(-89.0, 359.9999999) == (-89.0, 0.0)
    assert custom_point.normalise(10.1234567, 20.0) == (10.123457, 20.0)
    assert custom_point.label(-89.45, 222.69) == "Point 89.450° S, 222.690° E"
    site = custom_point.custom_site(-89.45, -137.31)
    assert site["site_id"] == "custom-point" and site["origin"] == "custom" and site["longitude_deg"] == 222.69


def test_resolve() -> None:
    catalogue = {"a": {"site_id": "a"}}
    assert custom_point.resolve("a", None, None, catalogue) == {"site_id": "a"}
    assert custom_point.resolve(None, -89.0, 10.0, catalogue)["site_id"] == "custom-point"
    for bad in (("nope", None, None), ("custom-point", None, None), (None, -89.0, None)):
        with pytest.raises(ValueError):
            custom_point.resolve(*bad, catalogue)


@pytest.mark.parametrize("model,extra", [
    (CheckRequest, {"start_utc": "2027-01-01T00:00:00Z"}),
    (LandingRequest, {"search_start_utc": "2027-01-01T00:00:00Z"}),
])
def test_request_takes_a_site_or_a_point(model: Any, extra: dict[str, Any]) -> None:
    assert model(site_id="x", **extra).latitude_deg is None
    assert model(latitude_deg=-89.4, longitude_deg=-40.0, **extra).site_id is None
    for bad in ({}, {"site_id": "x", "latitude_deg": -89.0, "longitude_deg": 1.0},
                {"latitude_deg": -89.0}, {"latitude_deg": -91.0, "longitude_deg": 0.0},
                {"latitude_deg": -89.0, "longitude_deg": 360.0}):
        with pytest.raises(ValidationError):
            model(**bad, **extra)


@pytest.mark.usefixtures("synthetic_service_environment")
def test_extra_sites_cannot_replace_catalogue() -> None:
    req = AnalysisRequest(site_ids=[TEST_SITE["site_id"]], start_utc="2027-01-01T00:00:00Z",
                          end_utc="2027-01-01T06:00:00Z", horizon_mode="flat")
    with pytest.raises(analysis_service.AnalysisNotReady, match="replace"):
        analysis_service.run_analysis(req, extra_sites={TEST_SITE["site_id"]: dict(TEST_SITE)})


@pytest.fixture
def seen_sites(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """(site_id, mode) per horizon build; terrain unavailable, as for a point outside the DEMs."""
    seen: list[tuple[str, str]] = []
    real = analysis_service._build_site_horizon

    def fake(site: Any, geometry: Any, request: Any, overrides: Any = None) -> Any:
        seen.append((site["site_id"], request.horizon_mode))
        if request.horizon_mode == "terrain":
            raise analysis_service.TerrainNotReady("no DEM here (test)")
        return real(site, geometry, request, overrides)

    monkeypatch.setattr(analysis_service, "_build_site_horizon", fake)
    return seen


@pytest.mark.usefixtures("synthetic_service_environment")
def test_check_at_a_point_matches_the_catalogue_site_at_the_same_place(seen_sites: list[tuple[str, str]]) -> None:
    lat, lon = float(TEST_SITE["latitude_deg"]), float(TEST_SITE["longitude_deg"])
    by_site = check.run_check(CheckRequest(site_id=TEST_SITE["site_id"], start_utc="2027-01-01T00:00:00Z", days=1))
    by_point = check.run_check(CheckRequest(latitude_deg=lat, longitude_deg=lon, start_utc="2027-01-01T00:00:00Z",
                                            days=1))
    assert by_point["site"]["site_id"] == "custom-point" and by_point["site"]["origin"] == "custom"
    assert ("custom-point", "terrain") in seen_sites  # terrain was attempted for the point too
    assert by_point["summary"]["numbers"] == by_site["summary"]["numbers"]
    assert by_point["cache_hit"] is False
    again = check.run_check(CheckRequest(latitude_deg=lat, longitude_deg=lon, start_utc="2027-01-01T00:00:00Z",
                                         days=1))
    assert again["cache_hit"] is True
    moved = check.run_check(CheckRequest(latitude_deg=lat, longitude_deg=(lon + 1.0) % 360.0,
                                         start_utc="2027-01-01T00:00:00Z", days=1))
    assert moved["cache_hit"] is False


@pytest.mark.usefixtures("synthetic_service_environment")
def test_landing_windows_at_a_point(seen_sites: list[tuple[str, str]]) -> None:
    lat, lon = float(TEST_SITE["latitude_deg"]), float(TEST_SITE["longitude_deg"])
    common = {"search_start_utc": "2027-01-01T00:00:00Z", "search_days": 2, "mission_days": 0.25}
    by_site = landing.run_landing(LandingRequest(site_id=TEST_SITE["site_id"], **common))
    by_point = landing.run_landing(LandingRequest(latitude_deg=lat, longitude_deg=lon, **common))
    assert by_point["site"]["site_id"] == "custom-point" and by_point["site"]["origin"] == "custom"
    assert by_point["opportunities"] == by_site["opportunities"]
    assert by_point["summary"][0].startswith("Next landing opportunity")
    # Flat fallback: the custom-point caveat (about 240 m terrain) is not shown, the fallback note is.
    assert not any("A point you picked" in c for c in by_point["caveats"])
    assert any("Terrain was not available" in c for c in by_point["caveats"])
