#!/usr/bin/env bash
# First real-terrain comparison: the same 30 days at three reference points, flat horizon vs
# NASA LOLA terrain. Requires reviewed DEMs (tools/review_dem.py --attest) and downloaded kernels.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"; elif [[ -x .venv/bin/python ]]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi
export PYTHONPATH="$ROOT:$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

"$PY" - <<'PY'
import math
import time

from lunar_core.analysis_service import run_analysis
from lunar_core.api_models import AnalysisRequest

SITES = ["reference-lola-site-001", "reference-lola-site-004", "reference-malapert-massif"]
common = dict(start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-31T00:00:00Z",
              coarse_step_min=30, event_tolerance_s=1.0)

results = {}
for mode in ("flat", "terrain"):
    t0 = time.perf_counter()
    run = run_analysis(AnalysisRequest(site_ids=SITES, horizon_mode=mode, **common))
    results[mode] = (run, time.perf_counter() - t0)
    print(f"{mode:7s} run {run['run_id']}  ({results[mode][1]:.1f} s)")

def hours(item):
    return f"{'>=' if item['display_prefix'] else ''}{item['duration_s'] / 3600:.1f} h"

print()
for index, site_id in enumerate(SITES):
    flat = results["flat"][0]["sites"][index]
    terr = results["terrain"][0]["sites"][index]
    print(f"== {terr['site']['name']}")
    for label, s in (("flat   ", flat), ("terrain", terr)):
        m, p = s["metrics"], s["event_precision"]
        print(f"  {label} sunlit {m['sunlit_percent']:5.1f}%  earth-visible {m['dte_clear_percent']:5.1f}%  "
              f"longest dark {hours(m['longest_darkness']):>9}  longest earth gap {hours(m['longest_dte_gap']):>9}  "
              f"certified {p['discovery_certified']}  grazes {len(p['sun_possible_grazing']) + len(p['earth_possible_grazing'])}")
    prof = [b for b in terr["horizon_profile"] if b["elevation_deg"] is not None]
    top = max(prof, key=lambda b: b["elevation_deg"])
    dists = sorted(b["controlling_distance_m"] for b in prof)
    terrain_meta = terr["terrain"]
    print(f"  horizon: max {top['elevation_deg']:.2f} deg at azimuth {top['azimuth_deg']:.1f} "
          f"(controlling ridge {top['controlling_distance_m'] / 1000:.1f} km away); "
          f"median controlling distance {dists[len(dists) // 2] / 1000:.1f} km; "
          f"ground {terrain_meta.get('site_ground_elevation_m', float('nan')):.1f} m; "
          f"assets {[a['asset_id'] for a in terrain_meta.get('assets', [])]}")
PY
