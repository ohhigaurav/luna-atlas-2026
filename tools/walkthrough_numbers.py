#!/usr/bin/env python3
"""Ask the live API the walkthrough's fixed questions and print the numbers the screen must show.

A step of the real-data walkthrough passes when the app shows the same numbers as the API for the
same question. This prints those numbers; it changes nothing.
Standard library only, so it runs on any laptop:

    python3 tools/walkthrough_numbers.py                       # live server, today 00:00 UTC
    python3 tools/walkthrough_numbers.py --base http://127.0.0.1:8000 --today 2026-11-14

The 365-day search can take a minute or more the first time on the server; later runs are cached.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

LIVE = "https://13-54-224-119.sslip.io"
SITE_001 = "reference-lola-site-001"
SITE_004 = "reference-lola-site-004"
COMPARE_AT = "2027-08-01T00:00:00Z"   # inside Site 001's 2027 landing season


def call(base: str, path: str, body: dict[str, Any] | None = None, timeout: float = 900) -> tuple[dict[str, Any], float]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), time.monotonic() - t0
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path}: HTTP {e.code} {e.read()[:300]!r}") from None


def pct(x: Any) -> str:
    return "-" if x is None else f"{float(x):.0f}%"


def days(h: Any) -> str:
    return "-" if h is None else f"{float(h) / 24:.1f} d"


def dh(h: Any) -> str:
    """Hours as the app shows them: "11 d 19 h" (rounded to the hour)."""
    if h is None or h == "-":
        return "-"
    n = round(float(h))
    return f"{n // 24} d {n % 24} h" if n >= 24 else f"{n} h"


def terrain(t: Any) -> str:
    r = (t or {}).get("finest_resolution_m")
    return "flat horizon" if r is None else f"{float(r):g} m terrain"


def window(o: dict[str, Any] | None) -> str:
    if not o:
        return "none"
    return (f"land {o.get('best_touchdown_utc', '?')[:16]}Z (window {o.get('touchdown_from_utc', '?')[:10]} .. "
            f"{o.get('touchdown_until_utc', '?')[:10]}), sunlight after {days(o.get('daylight_after_best_h'))}"
            f"{' or more' if o.get('daylight_is_lower_bound') else ''}, Earth {pct(o.get('earth_in_view_during_mission_pct'))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=LIVE)
    ap.add_argument("--today", default=dt.datetime.now(dt.UTC).strftime("%Y-%m-%d"),
                    help="UTC date the app treats as today (default: today)")
    a = ap.parse_args()
    today = f"{a.today}T00:00:00Z"

    h, _ = call(a.base, "/api/health")
    print(f"W1 health: {h.get('status')}  version {h.get('api_version')}  terrain ready {h.get('terrain_analysis_ready')}")
    idx, _ = call(a.base, "/api/site-index")
    print(f"W2 sites: {len(idx.get('sites', []))} ({idx.get('official_count')} official)")

    for sid in (SITE_001, SITE_004):
        r, s = call(a.base, "/api/landing-windows",
                    {"site_id": sid, "search_start_utc": today, "search_days": 90, "mission_days": 10})
        print(f"W3 {sid}, 90 d from {a.today}, 10-day mission: {terrain(r.get('terrain'))}, "
              f"computed in {r.get('compute_seconds')} s (round trip {s:.1f} s)")
        print(f"   soonest: {window(r.get('soonest'))}")
        miss = r.get("closest_miss")
        if miss and not r.get("soonest"):
            print(f"   no window; closest try {str(miss.get('touchdown_utc'))[:16]}Z fails {', '.join(miss.get('failed_rules', []))}")

    r, s = call(a.base, "/api/landing-windows",
                {"site_id": SITE_001, "search_start_utc": today, "search_days": 365, "mission_days": 10})
    print(f"W4 {SITE_001}, best date over 365 d: computed in {r.get('compute_seconds')} s (round trip {s:.1f} s)")
    for k, label in (("soonest", "soonest"), ("best", "most sunlight"), ("best_earth", "most Earth")):
        print(f"   {label:13s}: {window(r.get(k))}")

    c, s = call(a.base, "/api/compare", {"places": [{"site_id": SITE_001}, {"site_id": SITE_004}],
                                         "at_utc": COMPARE_AT, "days": 30, "panel_height_m": 2})
    print(f"W5 compare at {COMPARE_AT}, 30 days (round trip {s:.1f} s)")
    for row in c.get("rows", []):
        p = row.get("period", {})
        lb = " or more" if p.get("longest_darkness_lower_bound") else ""
        sn, en = row.get("sun_next") or {}, row.get("earth_next") or {}
        print(f"   {row.get('key')}: {terrain(row.get('terrain'))}; sunlit {pct(p.get('sunlit_percent'))}, "
              f"Earth {pct(p.get('earth_percent'))}, both {pct(p.get('both_percent'))}, "
              f"longest darkness {p.get('longest_darkness_h', 0):.0f} h{lb}; "
              f"next {sn.get('event', '-')} in {dh(sn.get('in_h'))}{' or more' if sn.get('lower_bound') else ''}, "
              f"next {en.get('event', '-')} in {dh(en.get('in_h'))}{' or more' if en.get('lower_bound') else ''}")
        pw = p.get("power")
        if pw:
            fr = pw.get("first_sunrise")
            rise = "no sunrise in the period" if not fr else (
                f"first sunrise {str(fr['sunrise_utc'])[:16]}Z: Sun set again before a full disc"
                if fr.get("set_before_full_disc") else
                f"first sunrise {str(fr['sunrise_utc'])[:16]}Z: full disc after {'at least ' if fr['lower_bound'] else ''}"
                f"{dh(fr['to_full_disc_h'])}")
            print(f"      power: {pw['mean_vertical_w_m2']:.0f} W/m2 average on a vertical panel "
                  f"({pw['mean_horizontal_w_m2']:.0f} flat), {pw['energy_vertical_kwh_m2']:.0f} kWh/m2 in 30 days, "
                  f"partial Sun {pw['partial_sun_percent']:.0f}% of the time; {rise}")

    for sid in (SITE_001, SITE_004):
        sl, s = call(a.base, "/api/slope", {"site_id": sid, "semi_major_m": 250, "slope_limit_deg": 8})
        area = sl.get("area") or {}
        print(f"W6 slope {sid}, 250 m ellipse, limit 8 deg: {sl.get('status')}; "
              f"{pct(100 * area['share_within_limit']) if 'share_within_limit' in area else '-'} within the limit; "
              f"chips {sl.get('chips')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
