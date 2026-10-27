#!/usr/bin/env bash
# Run portable checks. Missing optional static-analysis tools are reported as SKIPPED, never PASS.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT:$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
PYTHON_BIN="${PYTHON:-python3}"

printf '\n== Python compilation ==\n'
"$PYTHON_BIN" -m compileall -q backend/lunar_core tools
printf 'PASS: Python sources compile\n'

printf '\n== Test suite ==\n'
"$PYTHON_BIN" -m pytest -q

printf '\n== JavaScript syntax ==\n'
if command -v node >/dev/null 2>&1; then
  node --check frontend/app.js
  printf 'PASS: frontend/app.js parses\n'
else
  printf 'SKIPPED: Node.js is not installed\n'
fi

printf '\n== Ruff ==\n'
if command -v ruff >/dev/null 2>&1; then
  ruff check backend tests tools
else
  printf 'SKIPPED: ruff is not installed; CI installs it from the dev dependency group\n'
fi

printf '\n== mypy ==\n'
if command -v mypy >/dev/null 2>&1; then
  mypy backend/lunar_core
else
  printf 'SKIPPED: mypy is not installed; CI installs it from the dev dependency group\n'
fi

printf '\n== Catalogue integrity ==\n'
"$PYTHON_BIN" -m lunar_core.cli validate-catalogue
printf '\nVerification complete. A skipped static-analysis tool is not a passing check.\n'
