#!/usr/bin/env python3
"""Print landing opportunities for a few sites (real kernels and DEMs needed).

    .venv/bin/python tools/try_landing.py [--start 2027-01-01T00:00:00Z] [--days 90] [--mission 10]
                                          [--sites ID ...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

DEFAULT_SITES = ["reference-apollo-11", "reference-clps-blue-ghost-1", "reference-lola-site-001",
                 "reference-intl-chandrayaan-3"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2027-01-01T00:00:00Z")
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--mission", type=float, default=10.0)
    parser.add_argument("--sites", nargs="+", default=DEFAULT_SITES)
    args = parser.parse_args()

    from lunar_core.api_models import LandingRequest
    from lunar_core.landing import run_landing

    for site_id in args.sites:
        r = run_landing(LandingRequest(site_id=site_id, search_start_utc=args.start, search_days=args.days,
                                       mission_days=args.mission))
        print(f"\n== {r['site']['name']} ({r['horizon_mode']}, {r['compute_seconds']} s) ==")
        for line in r["summary"]:
            print("  " + line)
        for o in r["opportunities"][:6]:
            print(f"   - {o['touchdown_from_utc'][:16]} .. {o['touchdown_until_utc'][:16]}  best {o['best_touchdown_utc'][:16]}: "
                  f"{o['daylight_after_best_h'] / 24:.1f} d light, Sun {o['sun_elevation_at_best_deg']:.1f} deg, "
                  f"Earth {o['earth_in_view_during_mission_pct']:.0f}%")
        print(f"   candidates failing each rule: {r['candidates_failing']} of {r['candidates_checked']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
