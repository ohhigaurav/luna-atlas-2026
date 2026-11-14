"""Warm the landing-windows cache in the background (the app's green pins, PRD F24).

The app asks /api/landing-windows for every reference site with one default question: from
today 00:00 UTC, 90 days, a 10-day mission, Sun at most 20 deg up, Earth in view at touchdown
(frontend/app/src/plan/usePlan.ts). Answers are cached per request, and "today" changes at UTC
midnight, so the first opening of each UTC day would wait for all of them (~4 min on the team's
laptop, 5 Nov). This thread asks the same questions as soon as the server starts and again after
each UTC midnight, so the pins are ready when the browser opens.

Off unless LUNA_WARM_LANDING=1 (scripts/run_local.sh sets it); tests never start it. It goes
through the same run lock as every request, one site at a time, flat-horizon sites first.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger("lunar_core.warm")

# Must match the app's default question exactly, or the cache key differs.
SEARCH_DAYS = 90
MISSION_DAYS = 10.0
MAX_SUN_DEG = 20.0
POLAR_LIMIT_DEG = -60.0


def _today_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z")


def warm_once(day: str) -> tuple[int, int]:
    from lunar_core.api_models import LandingRequest
    from lunar_core.catalogue import load_default_catalogue
    from lunar_core.landing import run_landing
    from lunar_core.references import load_reference_catalogue

    # Official challenge sites first (none were published), then reference points; flat-horizon sites
    # before polar terrain sites within each group.
    official = [s for s in load_default_catalogue().sites if s.latitude_deg is not None and s.longitude_deg is not None]
    def polar(s: Any) -> bool:
        return s.latitude_deg is not None and s.latitude_deg <= POLAR_LIMIT_DEG

    sites: list[Any] = sorted(official, key=polar) + sorted(load_reference_catalogue().sites, key=polar)
    done = failed = 0
    for i, site in enumerate(sites, 1):
        started = time.monotonic()
        try:
            r = run_landing(LandingRequest.model_validate(
                {"site_id": site.site_id, "search_start_utc": day, "search_days": SEARCH_DAYS,
                 "mission_days": MISSION_DAYS, "max_sun_elevation_deg": MAX_SUN_DEG}))
            done += 1
            log.warning("warm %s %d/%d %s: %s in %.1f s", day[:10], i, len(sites), site.site_id,
                        "cached" if r.get("cache_hit") else f"{r.get('opportunity_count', 0)} windows", time.monotonic() - started)
        except Exception as exc:  # one bad site must not stop the rest; the app shows "not checked"
            failed += 1
            log.warning("warm %s %d/%d %s failed: %s", day[:10], i, len(sites), site.site_id, exc)
    return done, failed


def _loop() -> None:
    last = None
    while True:
        day = _today_utc()
        if day != last:
            warm_once(day)
            last = day
        time.sleep(300)


def start() -> None:
    threading.Thread(target=_loop, name="warm-landing", daemon=True).start()
