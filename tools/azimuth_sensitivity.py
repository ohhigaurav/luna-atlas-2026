#!/usr/bin/env python3
"""Does the 0.5 deg horizon azimuth step miss terrain? (independent review finding 10)

The horizon is one ray every ``terrain_azimuth_step_deg`` (default 0.5 deg), interpolated between
rays. A ridge narrower than one bin can fall between two rays. Here Sites 001 and 004 (5 m tiles)
are re-run at 0.25 deg, the finest the API allows, and compared with 0.5 deg.

Fixed before the first run (2026-11-06):
  * window 2027-01-01 to 01-31, 30 min step, terrain, Sun panel and antenna 2 m;
  * reported per site: sunlit %, disc-averaged Sun %, Earth %, at 0.5 and 0.25 deg, and the
    differences;
  * decision: if any |difference| exceeds 2 percentage points at either site, the default step
    becomes 0.25 deg (about twice the horizon build time). Otherwise 0.5 deg stays, and the
    sensitivity is recorded as measured.

    .venv/bin/python tools/azimuth_sensitivity.py
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

SITES = ("reference-lola-site-001", "reference-lola-site-004")
STEPS = (0.5, 0.25)
LIMIT_PTS = 2.0


def main() -> int:
    from lunar_core.analysis_service import run_analysis
    from lunar_core.api_models import AnalysisRequest
    from lunar_core.check import sun_disc_percent

    rows = []
    for site_id in SITES:
        out = {"site_id": site_id}
        for step in STEPS:
            run = run_analysis(AnalysisRequest(site_ids=[site_id], start_utc="2027-01-01T00:00:00Z",
                                               end_utc="2027-01-31T00:00:00Z", coarse_step_min=30, horizon_mode="terrain",
                                               sun_observer_height_m=2.0, antenna_height_m=2.0,
                                               terrain_azimuth_step_deg=step))
            s = run["sites"][0]
            out[str(step)] = {"sunlit": s["metrics"]["sunlit_percent"], "disc": sun_disc_percent(s["series"]),
                              "earth": s["metrics"]["dte_clear_percent"],
                              "bins": len(s.get("horizon_profile") or []),
                              "azimuth_step_recorded": (s.get("terrain") or {}).get("azimuth_step_deg")}
            print(f"  {site_id[-3:]} step {step:4.2f} deg: sun {out[str(step)]['sunlit']:6.2f}%  "
                  f"disc {out[str(step)]['disc']:6.2f}%  earth {out[str(step)]['earth']:6.2f}%  "
                  f"({out[str(step)]['bins']} horizon bins, step recorded {out[str(step)]['azimuth_step_recorded']})", flush=True)
        out["diff"] = {k: out["0.25"][k] - out["0.5"][k] for k in ("sunlit", "disc", "earth")}
        rows.append(out)
    worst = max(abs(v) for r in rows for v in r["diff"].values())
    print(f"\nlargest |0.25 - 0.5| difference: {worst:.2f} points (limit {LIMIT_PTS:g})")
    print("DECISION (fixed before the run): " + ("switch default to 0.25 deg" if worst > LIMIT_PTS else "keep 0.5 deg"))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = ROOT / "data" / "derived" / f"azimuth_sensitivity_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rows": rows, "worst_pts": worst, "limit_pts": LIMIT_PTS}, indent=2), encoding="utf-8")
    print(f"report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
