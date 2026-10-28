#!/usr/bin/env python3
"""Location-sensitivity scan: re-run the production analysis on a grid around each site.

Example (defaults: 300 m radius, 100 m spacing = 29 points, January 2027, 30 min step):

    python tools/location_scan.py reference-lola-site-004 reference-malapert-massif

For each site this prints the min / quartiles / max of sunlit %, Earth-visible % and
Sun+Earth %, where the published coordinate ranks among its neighbours, and a map of the grid
(north up, east right, centre marked with brackets). The full result, including every point's
coordinate and metrics, is saved under data/scans/<scan_id>.json.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))


def grid_map(points: list[dict[str, Any]], key: str, spacing: float) -> list[str]:
    """Rows of integer percentages, north at the top; '[..]' marks the centre, '  --' no data."""
    cells = {(round(p["east_m"] / spacing), round(p["north_m"] / spacing)): p for p in points}
    n = max(max(abs(i), abs(j)) for i, j in cells)
    lines = ["        " + "".join(f"{i * spacing:>+6.0f}" for i in range(-n, n + 1)) + "   (east, m)"]
    for j in range(n, -n - 1, -1):
        row = []
        for i in range(-n, n + 1):
            p = cells.get((i, j))
            if p is None:
                row.append("      ")
            elif p["status"] != "ok":
                row.append("    --")
            elif i == 0 and j == 0:
                row.append(f"  [{p[key]:3.0f}]"[-6:])
            else:
                row.append(f"{p[key]:6.0f}")
        lines.append(f"{j * spacing:>+6.0f}  " + "".join(row))
    lines.append("(north, m)")
    return lines


def fmt(entry: dict[str, Any], unit: str = "%") -> str:
    if entry["n"] == 0:
        return "no valid points"
    text = (f"min {entry['min']:6.1f}  p25 {entry['p25']:6.1f}  median {entry['median']:6.1f}  "
            f"p75 {entry['p75']:6.1f}  max {entry['max']:6.1f} {unit}")
    if entry.get("centre") is not None:
        rank = entry.get("fraction_of_points_below_centre")
        text += f"  | published point {entry['centre']:6.1f}"
        if rank is not None:
            text += f" (higher than {rank * 100:.0f}% of grid points)"
    return text


def main() -> int:
    from lunar_core.api_models import AnalysisRequest
    from lunar_core.location_scan import run_location_scan

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site_ids", nargs="+")
    parser.add_argument("--radius", type=float, default=300.0, help="scan radius in metres")
    parser.add_argument("--spacing", type=float, default=100.0, help="grid spacing in metres")
    parser.add_argument("--start", default="2027-01-01T00:00:00Z")
    parser.add_argument("--end", default="2027-01-31T00:00:00Z")
    parser.add_argument("--step-min", type=int, default=30)
    args = parser.parse_args()

    request = AnalysisRequest(
        site_ids=args.site_ids, horizon_mode="terrain", start_utc=args.start, end_utc=args.end,
        coarse_step_min=args.step_min, event_tolerance_s=1.0,
    )

    def progress(done: int, total: int, record: dict[str, Any]) -> None:
        if record["status"] == "ok":
            detail = (f"sunlit {record['sunlit_percent']:5.1f}%  earth {record['dte_clear_percent']:5.1f}%  "
                      f"ground {record['ground_elevation_m']:8.1f} m")
        else:
            detail = "unavailable: " + record["error"][:90]
        print(f"  [{done:3d}/{total}] E{record['east_m']:+5.0f} N{record['north_m']:+5.0f}  {detail}", flush=True)

    for site_id in args.site_ids:
        print(f"\n== {site_id}: radius {args.radius:.0f} m, spacing {args.spacing:.0f} m, {args.start} .. {args.end}")
        scan = run_location_scan(site_id, request, radius_m=args.radius, spacing_m=args.spacing, progress=progress)
        s = scan["summary"]
        print(f"\n  scan {scan['scan_id']}: {scan['points_ok']} points ok, {scan['points_unavailable']} unavailable, "
              f"all certified {scan['all_certified']}, {scan['elapsed_s']:.0f} s")
        print(f"  sunlit        {fmt(s['sunlit_percent'])}")
        print(f"  earth visible {fmt(s['dte_clear_percent'])}")
        print(f"  sun + earth   {fmt(s['both_percent'])}")
        print(f"  ground height {fmt(s['ground_elevation_m'], 'm')}")
        for key, label in (("sunlit_percent", "sunlit %"), ("dte_clear_percent", "earth-visible %")):
            print(f"\n  {label} map:")
            for line in grid_map(scan["points"], key, args.spacing):
                print("    " + line)
        print(f"\n  saved data/scans/{scan['scan_id']}.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
