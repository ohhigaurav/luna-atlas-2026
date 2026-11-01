#!/usr/bin/env bash
# Download the NASA SVS CGI Moon Kit maps (svs.gsfc.nasa.gov/4720) into public/textures/
# and convert the LOLA heights for the browser. Safe to re-run from any directory.
#
# Integrity: the first run writes scripts/textures.sha256; commit that file. Every later
# run (and every teammate's run) must reproduce the same bytes or the script fails.
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP"

BASE="https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720"
OUT="public/textures"
LOCK="scripts/textures.sha256"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/luna-atlas"
mkdir -p "$OUT" "$CACHE"

fetch() { # url dest: skip if already present
  if [[ -s "$2" ]]; then echo "have   $2"; return; fi
  echo "fetch  $1"
  curl -fL --retry 3 -o "$2.part" "$1"
  mv "$2.part" "$2"
}

fetch "$BASE/lroc_color_2k.jpg" "$OUT/lroc_color_2k.jpg"   # 2048x1024 sRGB colour, centred on 0 deg
fetch "$BASE/ldem_4.tif"        "$CACHE/ldem_4.tif"        # 1440x720 float32 km vs 1737.4 km

if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import numpy, tifffile' 2>/dev/null; then
  echo "setup  .venv (numpy, tifffile)"
  python -m venv .venv
  .venv/bin/pip install --quiet numpy tifffile
fi

if [[ ! -s "$OUT/lola_4ppd_f16.bin" ]]; then
  .venv/bin/python scripts/lola_to_f16.py "$CACHE/ldem_4.tif" "$OUT/lola_4ppd_f16.bin"
else
  echo "have   $OUT/lola_4ppd_f16.bin"
fi

FILES=("$OUT/lroc_color_2k.jpg" "$OUT/lola_4ppd_f16.bin")
SIZE=$(stat -c %s "$OUT/lola_4ppd_f16.bin")
if [[ "$SIZE" -ne $((1440 * 720 * 2)) ]]; then
  echo "error: lola_4ppd_f16.bin is $SIZE bytes, expected $((1440 * 720 * 2))" >&2; exit 1
fi

if [[ -f "$LOCK" ]]; then
  sha256sum -c "$LOCK"
  echo "ok     textures match $LOCK"
else
  sha256sum "${FILES[@]}" > "$LOCK"
  echo "wrote  $LOCK (first run). Commit it so every later download is checked:"
  cat "$LOCK"
fi
