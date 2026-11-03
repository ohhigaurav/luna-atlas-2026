#!/usr/bin/env bash
# Download the NASA maps the globe draws and convert them for the browser. Safe to re-run from
# any directory; downloads are cached in ~/.cache/luna-atlas and skipped when present.
#
#   Moon colour   SVS 4720 CGI Moon Kit, 2025 LROC map (16-bit sRGB TIFF)  -> moon_color_{8k,4k}.jpg
#   Moon relief   SVS 4720 LOLA ldem_16_uint.tif (16 px/deg)              -> lola_16ppd_f16_mips.bin
#                                                                            + polar caps (no pole streaks)
#   Earth         NASA Visible Earth Blue Marble, October 2004 (5400x2700) -> earth_bluemarble_5400.jpg
#
# MOON_RES=4k downloads the 4k colour TIFF (~50 MB) instead of 8k (~200 MB) for a quick setup.
#
# Integrity: the first run writes scripts/sources.sha256 (downloaded files) and
# scripts/textures.sha256 (the converted height maps, which are deterministic); commit both.
# Every later run must reproduce the same bytes or the script stops. The JPEGs depend on the
# local Pillow/libjpeg build, so they are not pinned; their source TIFF is.
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP"

SVS="https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720"
EARTH_URL="https://eoimages.gsfc.nasa.gov/images/imagerecords/74000/74167/world.200410.3x5400x2700.jpg"
OUT="public/textures"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/luna-atlas"
SRC_LOCK="$APP/scripts/sources.sha256"
OUT_LOCK="$APP/scripts/textures.sha256"
RES="${MOON_RES:-8k}"
mkdir -p "$OUT" "$CACHE"

fetch() { # url name-in-cache
  if [[ -s "$CACHE/$2" ]]; then echo "have   $2"; return; fi
  echo "fetch  $1"
  # NASA's servers sometimes drop long transfers: resume the partial file (-C -) and retry on any
  # error, so a cut-off 230 MB download continues instead of starting over.
  local n
  for n in 1 2 3 4 5 6; do
    if curl -fL -C - --retry 5 --retry-all-errors --retry-delay 3 -o "$CACHE/$2.part" "$1"; then
      mv "$CACHE/$2.part" "$CACHE/$2"; return
    fi
    echo "retry  $2 (attempt $n stopped; resuming)"; sleep 3
  done
  echo "error: could not download $1; run again to resume" >&2; exit 1
}

# check_or_pin lockfile dir file...: verify files already in the lock, add (and report) new ones.
check_or_pin() {
  local lock="$1" dir="$2"; shift 2
  touch "$lock"
  for f in "$@"; do
    if grep -q "  $f\$" "$lock"; then
      (cd "$dir" && grep "  $f\$" "$lock" | sha256sum -c --quiet -) || { echo "error: $f does not match $lock" >&2; exit 1; }
      echo "ok     $f"
    else
      (cd "$dir" && sha256sum "$f") >> "$lock"
      echo "pinned $f (first run; commit $(basename "$lock"))"
    fi
  done
}

COLOR_TIF="lroc_color_16bit_srgb_${RES}.tif"
fetch "$SVS/$COLOR_TIF"        "$COLOR_TIF"
fetch "$SVS/ldem_16_uint.tif"  "ldem_16_uint.tif"
fetch "$EARTH_URL"             "earth_bluemarble_5400.jpg"
check_or_pin "$SRC_LOCK" "$CACHE" "$COLOR_TIF" ldem_16_uint.tif earth_bluemarble_5400.jpg

if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import numpy, tifffile, PIL' 2>/dev/null; then
  echo "setup  .venv (numpy, tifffile, pillow, imagecodecs)"
  [[ -x .venv/bin/python ]] || python -m venv .venv
  .venv/bin/pip install --quiet numpy tifffile pillow
  .venv/bin/pip install --quiet imagecodecs || echo "note   imagecodecs not installed; fine unless a TIFF is compressed"
fi

if [[ ! -s "$OUT/moon_color_4k.jpg" ]]; then
  .venv/bin/python scripts/moon_color.py "$CACHE/$COLOR_TIF" "$OUT/moon_color"
else
  echo "have   $OUT/moon_color_4k.jpg"
fi

if [[ ! -s "$OUT/lola_16ppd_f16_mips.bin" || ! -s "$OUT/lola_cap_s_f16_mips.bin" || ! -s "$OUT/lola_cap_n_f16_mips.bin" ]]; then
  .venv/bin/python scripts/lola_to_f16.py "$CACHE/ldem_16_uint.tif" "$OUT/lola_16ppd_f16_mips.bin" --mips \
    --caps "$OUT/lola_cap" --cap-size 1536 --cap-lat 75
else
  echo "have   $OUT/lola_16ppd_f16_mips.bin and polar caps"
fi

cp -f "$CACHE/earth_bluemarble_5400.jpg" "$OUT/earth_bluemarble_5400.jpg"

check_or_pin "$OUT_LOCK" "$APP" "$OUT/lola_16ppd_f16_mips.bin" "$OUT/lola_cap_s_f16_mips.bin" "$OUT/lola_cap_n_f16_mips.bin"
echo "done   textures in $OUT"
