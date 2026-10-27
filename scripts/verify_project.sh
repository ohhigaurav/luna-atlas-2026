#!/usr/bin/env bash
# Run every portable check and report all results, even when an earlier check fails.
# A missing optional tool is reported as SKIPPED, never PASS. Exit status is non-zero if any
# check failed.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT:$ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
if [[ -n "${PYTHON:-}" ]]; then
  PYTHON_BIN="$PYTHON"
elif [[ -x .venv/bin/python ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

declare -a SUMMARY=()
FAILED=0

step() {
  local name="$1"; shift
  printf '\n== %s ==\n' "$name"
  if "$@"; then
    SUMMARY+=("PASS     $name")
  else
    SUMMARY+=("FAIL     $name")
    FAILED=1
  fi
}

skip() {
  printf '\n== %s ==\nSKIPPED: %s\n' "$1" "$2"
  SUMMARY+=("SKIPPED  $1 ($2)")
}

has_module() { "$PYTHON_BIN" -c "import $1" >/dev/null 2>&1; }

printf 'Python: %s (%s)\n' "$PYTHON_BIN" "$("$PYTHON_BIN" --version 2>&1)"

step "Python compilation" "$PYTHON_BIN" -m compileall -q backend/lunar_core tools
step "Test suite" "$PYTHON_BIN" -m pytest -q

if command -v node >/dev/null 2>&1; then
  step "JavaScript syntax" node --check frontend/app.js
else
  skip "JavaScript syntax" "Node.js is not installed"
fi

if has_module ruff; then
  step "Ruff" "$PYTHON_BIN" -m ruff check backend tests tools
else
  skip "Ruff" "ruff is not installed in this Python environment"
fi

if has_module mypy; then
  step "mypy" "$PYTHON_BIN" -m mypy backend/lunar_core
else
  skip "mypy" "mypy is not installed in this Python environment"
fi

step "Catalogue integrity" "$PYTHON_BIN" -m lunar_core.cli validate-catalogue

printf '\n== Summary ==\n'
printf '%s\n' "${SUMMARY[@]}"
if (( FAILED )); then
  printf '\nAt least one check FAILED.\n'
else
  printf '\nAll executed checks passed. A SKIPPED check is not a pass.\n'
fi
exit "$FAILED"
