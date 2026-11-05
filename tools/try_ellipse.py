#!/usr/bin/env python3
"""Landing-ellipse risk on real data (kernels + DEMs needed). Prints best / typical / worst.

    .venv/bin/python tools/try_ellipse.py [--sites ID ...] [--radius 250] [--start 2027-01-01T00:00:00Z] [--days 14]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sites", nargs="+", default=["reference-lola-site-004", "reference-lola-site-001"])
    parser.add_argument("--radius", type=float, default=250.0)
    parser.add_argument("--start", default="2027-01-01T00:00:00Z")
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()
    from lunar_core.api_models import EllipseRequest
    from lunar_core.landing_ellipse import run_landing_ellipse

    for site in args.sites:
        print(f"{site}: computing ...", flush=True)

        def tick(done: int, total: int, rec: dict) -> None:
            sun = rec.get("sunlit_percent")
            what = f"{sun:.0f}% sun" if sun is not None else rec.get("status")
            print(f"  point {done}/{total}: {rec['east_m']:+.0f} m E, {rec['north_m']:+.0f} m N -> {what}", flush=True)

        r = run_landing_ellipse(EllipseRequest(site_id=site, start_utc=args.start, days=args.days,
                                               semi_major_m=args.radius), progress=tick)
        risk, e = r["risk"], r["ellipse"]
        print(f"\n== {site}: {e['point_count']} points, {e['spacing_m']:.0f} m apart, radius {e['semi_major_m']:.0f} m "
              f"({r['compute_seconds']} s{', cached' if r['cache_hit'] else ''}) ==")
        print("  " + " · ".join(risk["chips"]))
        t = risk.get("target")
        if t:
            print(f"  target point: {t['sunlit_percent']:.1f}% sun, {t['dte_clear_percent']:.1f}% Earth")
        b = risk["best_point"]
        print(f"  best point: {b['east_m']:+.0f} m east, {b['north_m']:+.0f} m north -> {b['sunlit_percent']:.1f}% sun, "
              f"{b['dte_clear_percent']:.1f}% Earth")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
