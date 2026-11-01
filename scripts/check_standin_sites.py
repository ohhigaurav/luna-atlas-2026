#!/usr/bin/env python3
"""Real-data smoke run over the stand-in landing sites (needs kernels + DEMs on disk).

Polar sites run in terrain and flat mode; sites north of 60 S run flat only (no DEM, D-22).
Prints one line per site and the saved run IDs (data/runs/<run_id>.json).

    .venv/bin/python scripts/check_standin_sites.py
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from lunar_core.analysis_service import run_analysis  # noqa: E402
from lunar_core.api_models import AnalysisRequest  # noqa: E402

WINDOW = dict(start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-31T00:00:00Z",
              coarse_step_min=30, event_tolerance_s=1.0)
POLAR = ["reference-clps-im-1", "reference-clps-im-2",
         "reference-intl-chandrayaan-3", "reference-clps-cp-12-target"]
OTHER = ["reference-apollo-11", "reference-apollo-15", "reference-apollo-17", "reference-clps-blue-ghost-1",
         "reference-intl-change-4", "reference-intl-change-6", "reference-intl-slim", "reference-clps-im-3-target"]
RUNS = [("terrain", POLAR), ("flat", POLAR)] + [("flat", OTHER[i:i + 4]) for i in range(0, len(OTHER), 4)]


def pct(value: object) -> str:
    return f"{value:6.2f}%" if isinstance(value, (int, float)) else f"{value!s:>7}"


def main() -> int:
    failures = 0
    print(f"window {WINDOW['start_utc']} -> {WINDOW['end_utc']}, step {WINDOW['coarse_step_min']} min")
    print(f"{'mode':7s} {'site':32s} {'sunlit':>7s} {'earth':>7s} {'both':>7s}  run_id")
    for mode, ids in RUNS:
        started = time.monotonic()
        try:
            result = run_analysis(AnalysisRequest(site_ids=ids, horizon_mode=mode, **WINDOW))
        except Exception as exc:  # report and continue with the next batch
            failures += 1
            print(f"{mode:7s} FAILED for {ids}: {type(exc).__name__}: {exc}")
            traceback.print_exc(limit=3)
            continue
        for site in result["sites"]:
            m = site.get("metrics", {})
            print(f"{mode:7s} {site['site']['site_id']:32s} {pct(m.get('sunlit_percent', '?'))} "
                  f"{pct(m.get('dte_clear_percent', '?'))} {pct(m.get('both_percent', '?'))}  {result['run_id']}")
        print(f"        ({time.monotonic() - started:.0f} s)")
    print("done" if not failures else f"done with {failures} failed batch(es)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
