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

# The 3D app (frontend/app) is what / serves; the old four-screen app is frozen at /legacy.
# Build it when Node is installed and its source, textures or package files changed since the last
# build. A failed build never stops the API: / then explains how to build.
build_frontend() {
  local appdir="$ROOT/frontend/app" stamp="$ROOT/frontend/app/dist/index.html"
  [[ -f "$appdir/package.json" ]] || return 0
  if ! command -v npm >/dev/null 2>&1; then
    echo "note: npm not found, so the app is not built; / shows how (old app at /legacy)" >&2
    return 0
  fi
  if [[ -f "$stamp" ]] && [[ -z "$(find "$appdir/src" "$appdir/public" "$appdir/index.html" \
      "$appdir/package.json" "$appdir/vite.config.ts" -newer "$stamp" -print -quit 2>/dev/null)" ]]; then
    return 0
  fi
  if [[ ! -d "$appdir/node_modules" ]]; then
    if (( OFFLINE == 1 )); then
      echo "note: frontend/app/node_modules is missing; skipping the app build (--offline)" >&2
      return 0
    fi
    (cd "$appdir" && npm install --no-audit --no-fund) \
      || { echo "warning: npm install failed; / will show build instructions" >&2; return 0; }
  fi
  echo "Building the Luna Atlas app (frontend/app)..."
  (cd "$appdir" && npm run build) \
    || echo "warning: the app build failed (errors above); the API still starts" >&2
}
build_frontend

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
