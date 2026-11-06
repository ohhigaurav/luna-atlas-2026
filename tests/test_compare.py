"""Side-by-side comparison (lunar_core.compare): events, leaders, and the pipeline on synthetic geometry."""
from __future__ import annotations

from typing import Any

import pytest
from lunar_core import compare
from lunar_core.api_models import CompareRequest
from pydantic import ValidationError

from tests.test_analysis_service_integration import (  # noqa: F401
    TEST_SITE,
    synthetic_service_environment,
)
from tests.test_check import no_terrain  # noqa: F401


def w(start: float, end: float, *, st: bool = False, et: bool = False) -> dict[str, Any]:
    return {"start_et_s": start, "end_et_s": end, "start_utc": f"S{start:g}", "end_utc": f"E{end:g}",
            "start_truncated": st, "end_truncated": et}


def test_next_event_up_down_none_and_lower_bound() -> None:
    wins = [w(0, 3600, st=True), w(7200, 10800), w(14400, 18000, et=True)]
    up = compare.next_event(wins, 0.0, 18000, up_name="sunset", down_name="sunrise")
    assert up == {"up": True, "event": "sunset", "utc": "E3600", "in_h": 1.0, "lower_bound": False}
    down = compare.next_event(wins, 5400.0, 18000, up_name="sunset", down_name="sunrise")
    assert down["up"] is False and down["event"] == "sunrise" and down["in_h"] == pytest.approx(0.5)
    last = compare.next_event(wins, 15000.0, 18000, up_name="sunset", down_name="sunrise")
    assert last["up"] and last["lower_bound"] is True and last["in_h"] == pytest.approx(3000 / 3600)
    none = compare.next_event([], 0.0, 36000, up_name="earthset", down_name="earthrise")
    assert none["up"] is False and none["none_in_period"] and none["lower_bound"] and none["in_h"] == 10.0
    after = compare.next_event([w(0, 100)], 200.0, 3800, up_name="sunset", down_name="sunrise")
    assert after["none_in_period"] and after["in_h"] == 1.0


def _row(key: str, sun: float, earth: float, both: float, dark: float, sun_up: bool, sun_in: float,
         earth_up: bool, earth_in: float, el: float) -> dict[str, Any]:
    return {"site": {"site_id": key, "origin": "reference"},
            "period": {"sunlit_percent": sun, "earth_percent": earth, "both_percent": both, "longest_darkness_h": dark},
            "sun_next": {"up": sun_up, "in_h": sun_in}, "earth_next": {"up": earth_up, "in_h": earth_in},
            "now": {"sun": {"up": sun_up, "elevation_deg": el}}}


def test_leaders_ties_and_up_only() -> None:
    rows = [_row("a", 80, 50, 40, 10, True, 30, False, 5, 1.5),
            _row("b", 80, 60, 45, 20, False, 2, True, 100, -1.0),
            _row("c", 10, 60, 5, 300, True, 200, True, 50, 0.4)]
    lead = compare.leaders(rows)
    assert lead["most_sunlight"] == ["a", "b"] and lead["most_earth"] == ["b", "c"]
    assert lead["most_both"] == ["b"] and lead["shortest_darkness"] == ["a"]
    assert lead["longest_until_sunset"] == ["c"]          # b is down: not a candidate
    assert lead["longest_until_earthset"] == ["b"] and lead["highest_sun_now"] == ["a"]
    assert compare.leaders([_row("x", 0, 0, 0, 0, False, 0, False, 0, -5)])["highest_sun_now"] == []


def test_request_limits() -> None:
    ok = CompareRequest(places=[{"site_id": "a"}, {"latitude_deg": -89.4, "longitude_deg": 10}],
                        at_utc="2027-01-01T00:00:00Z")
    assert ok.days == 30 and ok.panel_height_m == 2.0
    for bad in ({"places": []}, {"places": [{"site_id": "a"}] * 7}, {"places": [{}]},
                {"places": [{"site_id": "a", "latitude_deg": -89.0, "longitude_deg": 0}]},
                {"at_utc": "2027-01-01T00:00:00"}, {"days": 61}, {"extra": 1}):
        with pytest.raises(ValidationError):
            CompareRequest(**{"places": [{"site_id": "a"}], "at_utc": "2027-01-01T00:00:00Z", **bad})


@pytest.mark.usefixtures("synthetic_service_environment", "no_terrain")
def test_compare_site_and_point_end_to_end() -> None:
    req = CompareRequest(places=[{"site_id": TEST_SITE["site_id"]},
                                 {"latitude_deg": TEST_SITE["latitude_deg"], "longitude_deg": 11.0}],
                         at_utc="2027-01-01T00:00:00Z", days=2)
    r = compare.run_compare(req)
    assert r["kind"] == "site_comparison" and len(r["rows"]) == 2
    a, b = r["rows"]
    assert a["key"] == TEST_SITE["site_id"] and b["site"]["origin"] == "custom" and b["key"] != a["key"]
    for row in r["rows"]:
        assert row["sun_next"]["event"] in ("sunset", "sunrise") and row["sun_next"]["in_h"] >= 0
        assert row["earth_next"]["event"] in ("earthset", "earthrise")
        assert row["now"]["sun"]["up"] == (row["sun_next"]["event"] == "sunset")
        assert row["verify"]["sun"]["horizons_url"].startswith("https://ssd.jpl.nasa.gov/")
        assert 0.0 <= row["period"]["sunlit_percent"] <= 100.0
    assert set(r["leaders"]) >= {"most_sunlight", "longest_until_earthset"}
    with pytest.raises(ValueError, match="twice"):
        compare.run_compare(CompareRequest(places=[{"site_id": TEST_SITE["site_id"]}] * 2,
                                           at_utc="2027-01-01T00:00:00Z", days=1))
