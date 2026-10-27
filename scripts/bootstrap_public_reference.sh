#!/usr/bin/env bash
# Fetches a starter set of NAIF kernels and NASA PGDA terrain files for the literature reference site.
# This does not populate official challenge sites or approve any DEM datum/frame assumptions.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="${PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x .venv/bin/python ]]; then PYTHON_BIN="$ROOT/.venv/bin/python"; else PYTHON_BIN="python3"; fi
fi
"$PYTHON_BIN" - <<'PY'
import importlib.util, sys
required = ["fastapi", "numpy", "pydantic", "pyproj", "rasterio", "scipy", "spiceypy", "uvicorn"]
missing = [name for name in required if importlib.util.find_spec(name) is None]
if missing:
    print("Missing runtime dependencies: " + ", ".join(missing), file=sys.stderr)
    print("Run ./scripts/run_local.sh once with package-registry access, then retry.", file=sys.stderr)
    sys.exit(2)
PY
exec "$PYTHON_BIN" tools/prepare_public_inputs.py "$@"
