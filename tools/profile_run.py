#!/usr/bin/env python3
"""Where does an analysis run spend its time? Profiles one real run, prints the top functions.

Default: LOLA Site 001, terrain, 30 days from 2027-01-01, 30 min step, 2 m. Run it twice:
the first run includes building the horizon (cached afterwards), the second shows the rest.

    .venv/bin/python tools/profile_run.py [--site ID] [--mode terrain|flat] [--days 30] [--tolerance 1]
"""
from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", default="reference-lola-site-001")
    parser.add_argument("--mode", choices=["terrain", "flat"], default="terrain")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--tolerance", type=float, default=1.0, help="event tolerance in seconds")
    parser.add_argument("--height", type=float, default=2.0)
    args = parser.parse_args()

    from lunar_core.analysis_service import run_analysis
    from lunar_core.api_models import AnalysisRequest

    start = datetime(2027, 1, 1, tzinfo=UTC)
    request = AnalysisRequest(site_ids=[args.site], start_utc=start, end_utc=start + timedelta(days=args.days),
                              coarse_step_min=30, event_tolerance_s=args.tolerance, horizon_mode=args.mode,
                              sun_observer_height_m=args.height)
    profiler = cProfile.Profile()
    t0 = time.monotonic()
    profiler.enable()
    result = run_analysis(request)
    profiler.disable()
    total = time.monotonic() - t0
    out = io.StringIO()
    pstats.Stats(profiler, stream=out).sort_stats("cumulative").print_stats(25)
    lines = [line for line in out.getvalue().splitlines() if line.strip()]
    print(f"{args.site} {args.mode} {args.days} d, tolerance {args.tolerance:g} s: {total:.1f} s total, "
          f"run {result['run_id']}, horizon cache hit: {result['sites'][0]['terrain'].get('cache_hit')}")
    print("\n".join(lines[:45]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
