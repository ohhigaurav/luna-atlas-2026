#!/usr/bin/env bash
# Make ONE file a teammate can run without touching the GitHub repo:
#   ~/luna-atlas-complete.tar.gz = the committed code (backend, frontend, scripts, docs; no .git,
#   no .venv, no node_modules) + the big local data that git does not carry (SPICE kernels, LOLA
#   terrain, Moon/Earth textures, LRO comparison pictures).
# The receiver follows RUN_ON_WINDOWS.md (WSL) or just runs scripts/run_local.sh on Linux/macOS.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
OUT="${1:-$HOME/luna-atlas-complete.tar.gz}"

if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "note: you have uncommitted changes; the package holds the last commit ($(git rev-parse --short HEAD)), not them" >&2
fi
need=(data/kernels data/dems/assets frontend/app/public/textures)
for d in "${need[@]}"; do
  if [[ -z "$(find "$d" -type f ! -name '.gitkeep' ! -name '.gitignore' ! -name 'README.md' -print -quit 2>/dev/null)" ]]; then
    echo "error: $d is empty here. Fetch it first (./scripts/bootstrap_public_reference.sh, cd frontend/app && npm run textures)" >&2
    exit 1
  fi
done
if [[ -d data/derived/shadow_match ]]; then python3 tools/export_proof.py >/dev/null || true; fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git archive --prefix=luna-atlas/ HEAD | tar -x -C "$TMP"
for d in "${need[@]}" frontend/app/public/proof; do
  [[ -d "$d" ]] || continue
  mkdir -p "$TMP/luna-atlas/$d"
  cp -a "$d/." "$TMP/luna-atlas/$d/"
done
git rev-parse HEAD > "$TMP/luna-atlas/PACKAGED_FROM_COMMIT.txt"
tar czf "$OUT" -C "$TMP" luna-atlas
echo "done: $OUT ($(du -h "$OUT" | cut -f1)), commit $(git rev-parse --short HEAD)"
echo "send that one file; the receiver follows RUN_ON_WINDOWS.md inside it"
