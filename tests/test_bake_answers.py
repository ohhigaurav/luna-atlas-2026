"""Plan of tools/bake_answers.py: what the static site will be able to answer."""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lunar_core.static_answers import make_key  # noqa: E402
from tools.bake_answers import plan  # noqa: E402

SITES = [{"site_id": "reference-lola-site-001", "latitude_deg": -89.45},
         {"site_id": "reference-lola-site-004", "latitude_deg": -89.78},
         {"site_id": "reference-apollo-11", "latitude_deg": 0.674}]


def test_plan_covers_the_app_requests_once() -> None:
    p = plan(SITES, datetime(2027, 1, 1, tzinfo=UTC))
    keys = [make_key(e, b) for e, b in p]
    assert len(keys) == len(set(keys))
    by = {e: sum(1 for x, _ in p if x == e) for e in ("landing-windows", "check", "compare", "landing-ellipse")}
    # polar: 2 ring checks + 5 mast heights; Apollo: 2 + 1
    assert by == {"landing-windows": 3 * 4, "check": 2 * 7 + 3, "compare": 3 * 4, "landing-ellipse": 2 * 4}
    # The landing request is exactly what the app's default question sends (usePlan / plan.ts).
    assert ("landing-windows?place=reference-apollo-11&search_start_utc=2027-01-01T00:00:00Z&search_days=90"
            "&mission_days=10&panel_height_m=2&require_earth_at_landing=true&max_sun_elevation_deg=20"
            "&min_sun_elevation_deg=auto") in keys
    assert "check?place=reference-lola-site-001&start_utc=2027-03-02T00:00:00Z&days=30&panel_height_m=2" in keys
