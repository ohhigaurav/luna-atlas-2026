#!/usr/bin/env python3
"""Terrain-uncertainty ensemble: rerun a site on PGDA error clones of its 5 m DEM.

Example (10 Site04 clones in data/dems/clones/Site04/):

    python tools/terrain_ensemble.py reference-lola-site-004 --asset pgda78-site04-surface \\
        --clones data/dems/clones/Site04/*.tif

Add --east/--north (metres) to evaluate a point offset from the published coordinate, e.g. a
location-scan grid point. Prints the nominal result, each clone's result and the spread; saves
data/ensembles/<ensemble_id>.json with every clone's SHA-256.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))


def main() -> int:
    from lunar_core.api_models import AnalysisRequest
    from lunar_core.location_scan import GridOffset
    from lunar_core.terrain_ensemble import run_terrain_ensemble

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site_id")
    parser.add_argument("--asset", required=True, help="DEM asset id the clones replace, e.g. pgda78-site04-surface")
    parser.add_argument("--clones", nargs="+", type=Path, required=True)
    parser.add_argument("--east", type=float, default=0.0)
    parser.add_argument("--north", type=float, default=0.0)
    parser.add_argument("--height", type=float, default=2.0, help="Sun observer and antenna height (m)")
    parser.add_argument("--start", default="2027-01-01T00:00:00Z")
    parser.add_argument("--end", default="2027-01-31T00:00:00Z")
    parser.add_argument("--step-min", type=int, default=30)
    args = parser.parse_args()

    request = AnalysisRequest(
        site_ids=[args.site_id], horizon_mode="terrain", start_utc=args.start, end_utc=args.end,
        coarse_step_min=args.step_min, event_tolerance_s=1.0,
        sun_observer_height_m=args.height, antenna_height_m=args.height,
    )

    def progress(done: int, total: int, record: dict[str, Any]) -> None:
        if record["status"] == "ok":
            detail = (f"sunlit {record['sunlit_percent']:5.1f}%  earth {record['dte_clear_percent']:5.1f}%  "
                      f"both {record['both_percent']:5.1f}%  ground {record['ground_elevation_m']:8.2f} m")
        else:
            detail = "unavailable: " + record["error"][:90]
        print(f"  [{done:3d}/{total}] {record['member']:10s} {detail}", flush=True)

    clones = sorted(args.clones)
    print(f"== {args.site_id} at E{args.east:+.0f} N{args.north:+.0f} m, height {args.height} m, "
          f"{len(clones)} clones of {args.asset}, {args.start} .. {args.end}")
    result = run_terrain_ensemble(
        args.site_id, request, asset_id=args.asset, clone_paths=clones,
        offset=GridOffset(args.east, args.north), progress=progress,
    )
    print(f"\n  ensemble {result['ensemble_id']}: {result['members_ok']}/{result['member_count']} ok, "
          f"all certified {result['all_certified']}, {result['elapsed_s']:.0f} s")
    for key, label in (("sunlit_percent", "sunlit %"), ("dte_clear_percent", "earth %"), ("both_percent", "both %")):
        s = result["summary"][key]
        if s["n"] == 0:
            print(f"  {label:9s} no valid clones")
            continue
        print(f"  {label:9s} nominal {s['nominal']:5.1f} | clones min {s['min']:5.1f}  p25 {s['p25']:5.1f}  "
              f"median {s['median']:5.1f}  p75 {s['p75']:5.1f}  max {s['max']:5.1f} | "
              f"non-zero in {s['fraction_of_clones_nonzero'] * 100:.0f}% of clones, "
              f"largest change {s['max_abs_change_vs_nominal']:.1f} points")
    for line in result["limits"]:
        print(f"  limit: {line}")
    print(f"  saved data/ensembles/{result['ensemble_id']}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
