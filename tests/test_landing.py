"""Landing opportunities: rule logic on hand-made windows, and the full pipeline on synthetic geometry."""
from __future__ import annotations

from typing import Any

import pytest
from lunar_core import analysis_service, landing
from lunar_core.api_models import LandingRequest
from lunar_core.landing import Sample, Window
from pydantic import ValidationError

from tests.test_analysis_service_integration import (  # noqa: F401
    TEST_SITE,
    synthetic_service_environment,
)

H = 3600.0
D = 86400.0


def _w(a_h: float, b_h: float, open_end: bool = False) -> Window:
    return Window(a_h * H, b_h * H, f"t{a_h:g}", f"t{b_h:g}", open_end)


def _samples(n_hours: int, sun: list[Window], earth: list[Window], el: float = 5.0) -> list[Sample]:
    inside = lambda ws, t: any(w.start_s <= t < w.end_s for w in ws)  # noqa: E731
    return [Sample(h * H, f"h{h}", inside(sun, h * H), el,
                   inside(earth, h * H)) for h in range(n_hours)]


def _eval(samples: list[Sample], sun: list[Window], earth: list[Window], **kw: Any) -> dict[str, Any]:
    args = {"mission_days": 1.0, "require_earth": True, "max_sun_el_deg": 20.0,
            "search_end_s": samples[-1].t_s, "step_s": H} | kw
    return landing.evaluate(samples, sun, earth, **args)


def test_opportunity_is_the_span_with_enough_daylight_left() -> None:
    sun, earth = [_w(10, 80)], [_w(0, 100)]
    r = _eval(_samples(100, sun, earth), sun, earth, mission_days=2.0)  # need 48 h before sunset at 80 h
    assert r["opportunity_count"] == 1
    o = r["opportunities"][0]
    assert (o["touchdown_from_utc"], o["touchdown_until_utc"]) == ("h10", "h32")
    assert o["daylight_after_best_h"] == 70.0 and o["sunset_utc"] == "t80"
    assert o["earth_in_view_during_mission_pct"] == 100.0


def test_each_rule_can_block_and_closest_miss_names_it() -> None:
    sun, earth = [_w(10, 30)], [_w(0, 100)]
    r = _eval(_samples(60, sun, earth), sun, earth, mission_days=2.0)  # only 20 h of sun
    assert r["opportunity_count"] == 0
    assert r["closest_miss"]["failed_rules"] == ["daylight"]
    assert r["closest_miss"]["daylight_after_h"] == 20.0
    text = " ".join(landing.explain(r, mission_days=2.0, site_name="X"))
    assert "0.8 days of sunlight; you asked for 2" in text and "longest stretch of sunlight here is 0.8 days" in text

    sun, earth = [_w(0, 100)], []
    r = _eval(_samples(60, sun, earth), sun, earth)
    assert r["closest_miss"]["failed_rules"] == ["earth_up"] and r["candidates_failing"]["earth_up"] == 60
    assert _eval(_samples(60, sun, earth), sun, earth, require_earth=False)["opportunity_count"] == 1

    sun, earth = [_w(0, 100)], [_w(0, 100)]
    r = _eval(_samples(60, sun, earth, el=30.0), sun, earth)
    assert r["closest_miss"]["failed_rules"] == ["low_sun"]
    assert _eval(_samples(60, sun, earth, el=30.0), sun, earth, max_sun_el_deg=None)["opportunity_count"] == 1


def test_never_sunlit() -> None:
    r = _eval(_samples(48, [], [_w(0, 48)]), [], [_w(0, 48)])
    assert r["longest_sunlit_window"] is None
    assert "never rises" in " ".join(landing.explain(r, mission_days=1, site_name="X"))


def test_two_separate_opportunities_and_open_window_is_a_lower_bound() -> None:
    sun, earth = [_w(0, 30), _w(60, 200, open_end=True)], [_w(0, 200)]
    r = _eval(_samples(120, sun, earth), sun, earth, mission_days=0.5, search_end_s=119 * H)
    assert r["opportunity_count"] == 2
    second = r["opportunities"][1]
    assert second["daylight_is_lower_bound"] is True and second["sunset_utc"] is None
    assert "at least" in " ".join(landing.explain({**r, "opportunities": r["opportunities"][1:]},
                                                   mission_days=0.5, site_name="X"))


def test_merge_joins_chunk_seams_only() -> None:
    def raw(a: float, b: float, st: bool, et: bool) -> dict[str, Any]:
        return {"start_et_s": a, "end_et_s": b, "start_utc": f"u{a:g}", "end_utc": f"u{b:g}",
                "start_truncated": st, "end_truncated": et}
    merged = landing.merge_windows([[raw(0, 5, True, False), raw(8, 10, False, True)],
                                    [raw(10, 20, True, False), raw(30, 40, False, True)]])
    assert [(w.start_s, w.end_s, w.end_open) for w in merged] == [(0, 5, False), (8, 20, False), (30, 40, True)]
    assert merged[1].start_utc == "u8" and merged[1].end_utc == "u20"


def test_request_limits() -> None:
    ok = LandingRequest(site_id="x", search_start_utc="2027-01-01T00:00:00Z")
    assert (ok.search_days, ok.mission_days, ok.max_sun_elevation_deg) == (90, 10.0, 20.0)
    for bad in ({"search_days": 181}, {"mission_days": 0.1}, {"search_start_utc": "2027-01-01T00:00:00"},
                {"horizon_mode": "flat"}):
        with pytest.raises(ValidationError):
            LandingRequest(**{"site_id": "x", "search_start_utc": "2027-01-01T00:00:00Z", **bad})


@pytest.mark.usefixtures("synthetic_service_environment")
def test_full_pipeline_on_synthetic_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    # Synthetic Sun: up 6 h of every 12 h at +/-5.7 deg; Earth always up. Polar test site -> terrain is
    # attempted first; make it unavailable so the flat fallback and its caveat are exercised too.
    real = analysis_service._build_site_horizon

    def no_terrain(site: Any, geometry: Any, request: Any, overrides: Any = None) -> Any:
        if request.horizon_mode == "terrain":
            raise analysis_service.TerrainNotReady("no DEM (test)")
        return real(site, geometry, request, overrides)

    monkeypatch.setattr(analysis_service, "_build_site_horizon", no_terrain)
    req = LandingRequest(site_id=TEST_SITE["site_id"], search_start_utc="2027-01-01T00:00:00Z",
                         search_days=2, mission_days=0.25)
    r = landing.run_landing(req)
    assert r["horizon_mode"] == "flat" and any("Terrain was not available" in c for c in r["caveats"])
    assert r["opportunity_count"] >= 3
    for o in r["opportunities"]:
        assert o["daylight_after_best_h"] >= 6.0 - 0.6 and o["earth_in_view_during_mission_pct"] == 100.0
    assert r["summary"][0].startswith("Next landing opportunity")
    long = landing.run_landing(req.model_copy(update={"mission_days": 1.0}))
    assert long["opportunity_count"] == 0 and long["closest_miss"]["failed_rules"] == ["daylight"]
