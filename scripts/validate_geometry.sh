#!/usr/bin/env bash
# Gate B: run a fresh 30-day flat-horizon analysis for two reference points and compare its
# Sun/Earth geometry with JPL Horizons under the D-10 tolerances approved beforehand.
# Needs: installed dependencies, downloaded kernels, and internet access to ssd.jpl.nasa.gov.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ -n "${PYTHON:-}" ]]; then PY="$PYTHON"; elif [[ -x .venv/bin/python ]]; then PY="$ROOT/.venv/bin/python"; else PY=python3; fi
export PYTHONPATH="$ROOT:$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"

RUN_JSON="$("$PY" - <<'PY'
from lunar_core.analysis_service import RUNS_DIR, run_analysis
from lunar_core.api_models import AnalysisRequest

result = run_analysis(AnalysisRequest(
    site_ids=["reference-malapert-massif", "reference-lola-site-001"],
    start_utc="2027-01-01T00:00:00Z", end_utc="2027-01-31T00:00:00Z",
    coarse_step_min=30, event_tolerance_s=1.0, horizon_mode="flat",
))
print(RUNS_DIR / f"{result['run_id']}.json")
PY
)"
echo "fresh run: $RUN_JSON"
"$PY" tools/horizons_golden.py "$RUN_JSON"
