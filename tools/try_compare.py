#!/usr/bin/env python3
"""Print a side-by-side comparison (real kernels and DEMs needed).

    .venv/bin/python tools/try_compare.py [--at 2027-01-10T00:00:00Z] [--days 30]
                                          [--sites ID ...] [--point LAT LON ...]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

DEFAULT_SITES = ["reference-lola-site-001", "reference-lola-site-004", "reference-malapert-massif"]


def _h(hours: float, lower: bool) -> str:
    d, h = divmod(int(hours), 24)
    text = f"{d} d {h} h" if d else f"{hours:.1f} h"
    return ("≥ " if lower else "") + text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--at", default="2027-01-10T00:00:00Z")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--sites", nargs="+", default=None)
    parser.add_argument("--point", nargs=2, type=float, action="append", metavar=("LAT", "LON"))
    args = parser.parse_args()
    places: list[dict[str, object]] = [{"site_id": s} for s in (args.sites or ([] if args.point else DEFAULT_SITES))]
    places += [{"latitude_deg": a, "longitude_deg": b} for a, b in (args.point or [])]

    from lunar_core.api_models import CompareRequest
    from lunar_core.compare import run_compare

    r = run_compare(CompareRequest(places=places, at_utc=args.at, days=args.days))
    print(f"Compare at {r['at_utc']} over {r['days']} days (panel {r['panel_height_m']} m, antenna {r['antenna_height_m']} m)\n")
    for row in r["rows"]:
        s, n, sn, en, p = row["site"], row["now"], row["sun_next"], row["earth_next"], row["period"]
        print(f"== {s['name']} [{row['horizon_mode']}] ==")
        print(f"  now:   Sun {'UP' if n['sun']['up'] else 'down'} {n['sun']['elevation_deg']:+.2f}° "
              f"(horizon {n['sun']['horizon_deg']:+.2f}°) | Earth {'UP' if n['earth']['up'] else 'down'} "
              f"{n['earth']['elevation_deg']:+.2f}° (horizon {n['earth']['horizon_deg']:+.2f}°)")
        print(f"  next:  {sn['event']} in {_h(sn['in_h'], sn['lower_bound'])} | {en['event']} in {_h(en['in_h'], en['lower_bound'])}")
        print(f"  {r['days']} d:  sun {p['sunlit_percent']:.0f}%  earth {p['earth_percent']:.0f}%  both {p['both_percent']:.0f}%  "
              f"longest dark {_h(p['longest_darkness_h'], p['longest_darkness_lower_bound'])}")
    print("\nleaders:", {k: v for k, v in r["leaders"].items() if v})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
