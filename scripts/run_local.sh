#!/usr/bin/env bash
# Bootstrap and run the local app. Use --offline after dependencies are already installed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
OFFLINE=0
if [[ "${1:-}" == "--offline" || "${1:-}" == "--no-install" ]]; then
  OFFLINE=1
elif [[ -n "${1:-}" ]]; then
  echo "Usage: $0 [--offline]" >&2
  exit 2
fi

if (( OFFLINE == 0 )); then
  if command -v uv >/dev/null 2>&1; then
    uv sync
    exec uv run --no-sync uvicorn lunar_core.api:app --app-dir backend --host "$HOST" --port "$PORT"
  else
    PYTHON_BIN="${PYTHON:-python3}"
    if [[ ! -x .venv/bin/python ]]; then
      "$PYTHON_BIN" -m venv .venv
    fi
    .venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
    exec env PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" .venv/bin/python -m uvicorn \
      lunar_core.api:app --host "$HOST" --port "$PORT"
  fi
fi

# Offline path never attempts dependency installation or registry access.
if [[ -x .venv/bin/python ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="${PYTHON:-python3}"
fi
if ! "$PYTHON_BIN" -c 'import fastapi, numpy, pydantic, pyproj, rasterio, scipy, uvicorn' >/dev/null 2>&1; then
  cat >&2 <<'MESSAGE'
The offline UI requires the core web/science Python dependencies to be installed.
Run ./scripts/run_local.sh once while the package registry is reachable, or install
requirements.txt into your chosen Python environment. SpiceyPy is additionally required
for real ephemeris analysis; if it is absent, the UI/UX preview remains available and
real-analysis requests fail explicitly instead of fabricating results.
MESSAGE
  exit 1
fi
exec env PYTHONPATH="$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}" "$PYTHON_BIN" -m uvicorn \
  lunar_core.api:app --host "$HOST" --port "$PORT"
