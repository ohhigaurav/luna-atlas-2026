"""Horizons "verify" links (lunar_core.verify) and their place in check / landing responses."""
from __future__ import annotations

import urllib.parse

import pytest
from lunar_core import check, landing, verify
from lunar_core.api_models import CheckRequest, LandingRequest

from tests.test_analysis_service_integration import (  # noqa: F401
    TEST_SITE,
    synthetic_service_environment,
)
from tests.test_check import no_terrain  # noqa: F401


def _params(url: str) -> dict[str, str]:
    base, query = url.split("?", 1)
    assert base == "https://ssd.jpl.nasa.gov/api/horizons.api"
    return dict(urllib.parse.parse_qsl(query))


def test_url_matches_gate_b_settings() -> None:
    p = _params(verify.horizons_url("SUN", -89.45, -137.31, 1950.0, "2027-01-01T12:00:00Z"))
    assert p["format"] == "text" and p["COMMAND"] == "'10'" and p["CENTER"] == "'coord@301'"
    assert p["SITE_COORD"] == "'222.690000,-89.450000,1.950000'"
    assert p["QUANTITIES"] == "'4,20'" and p["APPARENT"] == "'AIRLESS'" and p["TIME_TYPE"] == "'UT'"
    # 2027-01-01 12:00 UT = JD 2461407.0
    assert p["TLIST"] == "'2461407.000000000'"
    assert _params(verify.horizons_url("EARTH", 0, 0, 0, "2027-01-01T00:00:00Z"))["COMMAND"] == "'399'"
    with pytest.raises(ValueError):
        verify.horizons_url("MARS", 0, 0, 0, "2027-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        verify.horizons_url("SUN", 0, 0, 0, "2027-01-01T00:00:00")


def test_block_uses_ground_plus_height() -> None:
    site_result = {"site": {"latitude_deg": -89.0, "longitude_deg": 10.0},
                   "terrain": {"site_ground_elevation_m": 1200.5}}
    row = {"utc": "2027-01-01T00:00:00Z", "sun_azimuth_deg": 12.345678, "sun_elevation_deg": 1.5,
           "earth_azimuth_deg": 3.0, "earth_elevation_deg": 4.0}
    b = verify.verify_block(site_result, row, sun_height_m=2.0, antenna_height_m=10.0)
    assert b["sun"]["observer_altitude_m"] == 1202.5 and b["earth"]["observer_altitude_m"] == 1210.5
    assert b["sun"]["ours_azimuth_deg"] == 12.3457
    assert _params(b["earth"]["horizons_url"])["SITE_COORD"] == "'10.000000,-89.000000,1.210500'"
    flat = verify.verify_block({"site": site_result["site"], "terrain": {}}, row, sun_height_m=0.0,
                               antenna_height_m=0.0)
    assert flat["sun"]["observer_altitude_m"] == 0.0


@pytest.mark.usefixtures("synthetic_service_environment", "no_terrain")
def test_check_and_landing_carry_verify_links() -> None:
    c = check.run_check(CheckRequest(site_id=TEST_SITE["site_id"], start_utc="2027-01-01T00:00:00Z", days=1))
    assert c["verify"]["utc"] == "2027-01-01T00:00:00Z"
    assert c["verify"]["sun"]["horizons_url"].startswith(verify.HORIZONS_API)
    r = landing.run_landing(LandingRequest(site_id=TEST_SITE["site_id"], search_start_utc="2027-01-01T00:00:00Z",
                                           search_days=2, mission_days=0.25))
    assert r["opportunities"]
    for o in r["opportunities"]:
        assert o["verify"]["utc"] == o["best_touchdown_utc"]
        assert o["verify"]["sun"]["ours_elevation_deg"] == pytest.approx(o["sun_elevation_at_best_deg"], abs=1e-4)
