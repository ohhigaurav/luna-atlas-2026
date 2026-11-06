#!/usr/bin/env python3
"""Print landing opportunities for a few sites (real kernels and DEMs needed).

    .venv/bin/python tools/try_landing.py [--start 2027-01-01T00:00:00Z] [--days 90] [--mission 10]
                                          [--sites ID ...] [--point LAT LON ...]
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
    parser.add_argument("--sites", nargs="+", default=None)
    parser.add_argument("--point", nargs=2, type=float, action="append", metavar=("LAT", "LON"),
                        help="a custom point (repeatable); planetocentric lat, east lon")
    args = parser.parse_args()
    targets: list[dict[str, object]] = [{"site_id": s} for s in (args.sites or ([] if args.point else DEFAULT_SITES))]
    targets += [{"latitude_deg": lat, "longitude_deg": lon} for lat, lon in (args.point or [])]

    from lunar_core.api_models import LandingRequest
    from lunar_core.landing import run_landing

    for target in targets:
        r = run_landing(LandingRequest(**target, search_start_utc=args.start, search_days=args.days,
                                       mission_days=args.mission))
        print(f"\n== {r['site']['name']} ({r['horizon_mode']}, {r['compute_seconds']} s) ==")
        for line in r["summary"]:
            print("  " + line)
        for o in r["opportunities"][:6]:
            print(f"   - {o['touchdown_from_utc'][:16]} .. {o['touchdown_until_utc'][:16]}  best {o['best_touchdown_utc'][:16]}: "
                  f"{o['daylight_after_best_h'] / 24:.1f} d light, Sun {o['sun_elevation_at_best_deg']:.1f} deg"
                  + (f" ({o['sun_above_horizon_at_best_deg']:+.1f} above local horizon)"
                     if o.get("sun_above_horizon_at_best_deg") is not None else "") + ", "
                  f"Earth {o['earth_in_view_during_mission_pct']:.0f}%")
        print(f"   candidates failing each rule: {r['candidates_failing']} of {r['candidates_checked']}")
        for c in r["caveats"]:
            print(f"   ! {c}")
        first = r["opportunities"][0] if r["opportunities"] else r["closest_miss"]
        if first and first.get("verify"):
            v = first["verify"]["sun"]
            print(f"   verify {first['verify']['utc'][:16]}: ours Sun az {v['ours_azimuth_deg']:.4f} "
                  f"el {v['ours_elevation_deg']:.4f} -> {v['horizons_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
