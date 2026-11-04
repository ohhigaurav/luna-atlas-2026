#!/usr/bin/env bash
# Download the NASA maps the globe draws and convert them for the browser. Safe to re-run from
# any directory; downloads are cached in ~/.cache/luna-atlas and skipped when present.
#
#   Moon colour   SVS 4720 CGI Moon Kit, 2025 LROC map (16-bit sRGB TIFF)  -> moon_color_{8k,4k}.jpg
#   Moon relief   SVS 4720 LOLA ldem_16_uint.tif (16 px/deg)              -> lola_16ppd_f16_mips.bin
#                                                                            + polar caps (no pole streaks)
#   Earth         NASA Blue Marble Next Generation, 5400x2700             -> earth_bluemarble_5400.jpg
#                 (optional: if no source answers, the globe draws a plain Earth and says nothing false)
#
# MOON_RES=4k downloads the 4k colour TIFF (~50 MB) instead of 8k (~230 MB).
# MOON_RES=lite needs ~4.5 MB in total (2k colour JPEG + 4 px/deg heights; no Earth image) and
# reuses files an older run already left behind: for slow connections. Rerun without it later.
# Every mode writes public/textures/textures.json, the list of maps the app should load.
#
# Integrity: the first run writes scripts/sources.sha256 (downloaded files) and
# scripts/textures.sha256 (the converted height maps, which are deterministic); commit both.
# Every later run must reproduce the same bytes or the script stops. The JPEGs depend on the
# local Pillow/libjpeg build, so they are not pinned; their source TIFF is.
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP"

SVS="https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720"
# The Blue Marble moved from eoimages.gsfc.nasa.gov to science.nasa.gov in 2025 (NEO archive README);
# the old host is kept as a second try. First: August 2004 with topography and bathymetry shading.
# The new host is an image-resizing service: ask it for an explicit JPEG size (without parameters it
# sent a 132 KB preview). The second URL is the one NASA's own page uses. Earth spans a few dozen
# pixels on screen, so 2048-4096 px is far more than enough.
BMNG="https://assets.science.nasa.gov/dynamicimage/assets/science/esd/eo/images/bmng/bmng-topography-bathymetry/august/world.topo.bathy.200408.3x5400x2700.jpg"
EARTH_URLS=(
  "$BMNG?w=4096&h=2048&fit=clip&fm=jpg&q=90"
  "$BMNG?w=2048&h=1024&fit=clip&crop=faces%2Cfocalpoint"
  "https://eoimages.gsfc.nasa.gov/images/imagerecords/74000/74167/world.200410.3x5400x2700.jpg"
)
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

ensure_venv() {
  if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import numpy, tifffile, PIL' 2>/dev/null; then
    echo "setup  .venv (numpy, tifffile, pillow, imagecodecs)"
    [[ -x .venv/bin/python ]] || python -m venv .venv
    .venv/bin/pip install --quiet numpy tifffile pillow
    .venv/bin/pip install --quiet imagecodecs || echo "note   imagecodecs not installed; fine unless a TIFF is compressed"
  fi
}

if [[ "$RES" == "lite" ]]; then
  # Reuse what an older run of this script left (public/textures/lroc_color_2k.jpg).
  [[ -s "$CACHE/lroc_color_2k.jpg" || ! -s "$OUT/lroc_color_2k.jpg" ]] || cp "$OUT/lroc_color_2k.jpg" "$CACHE/lroc_color_2k.jpg"
  fetch "$SVS/lroc_color_2k.jpg" lroc_color_2k.jpg
  fetch "$SVS/ldem_4.tif"        ldem_4.tif
  check_or_pin "$SRC_LOCK" "$CACHE" lroc_color_2k.jpg ldem_4.tif
  ensure_venv
  cp -f "$CACHE/lroc_color_2k.jpg" "$OUT/moon_color_2k.jpg"
  if [[ ! -s "$OUT/lola_4ppd_f16_mips.bin" || ! -s "$OUT/lola_cap4_s_f16_mips.bin" ]]; then
    .venv/bin/python scripts/lola_to_f16.py "$CACHE/ldem_4.tif" "$OUT/lola_4ppd_f16_mips.bin" --mips \
      --caps "$OUT/lola_cap4" --cap-size 512 --cap-lat 75
  fi
  check_or_pin "$OUT_LOCK" "$APP" "$OUT/lola_4ppd_f16_mips.bin" "$OUT/lola_cap4_s_f16_mips.bin" "$OUT/lola_cap4_n_f16_mips.bin"
  EARTH='null'
  [[ -s "$OUT/earth_bluemarble_5400.jpg" ]] && EARTH='"earth_bluemarble_5400.jpg"'
  cat > "$OUT/textures.json" <<JSON
{"set": "lite",
 "moon_color": [{"file": "moon_color_2k.jpg", "width": 2048}],
 "heights": {"file": "lola_4ppd_f16_mips.bin", "width": 1440, "height": 720},
 "caps": {"south": "lola_cap4_s_f16_mips.bin", "north": "lola_cap4_n_f16_mips.bin", "size": 512, "lat": 75},
 "earth": $EARTH}
JSON
  echo "done   lite textures in $OUT (run without MOON_RES=lite on a fast connection for 8k)"
  exit 0
fi

COLOR_TIF="lroc_color_16bit_srgb_${RES}.tif"
fetch "$SVS/$COLOR_TIF"        "$COLOR_TIF"
fetch "$SVS/ldem_16_uint.tif"  "ldem_16_uint.tif"
check_or_pin "$SRC_LOCK" "$CACHE" "$COLOR_TIF" ldem_16_uint.tif

# Earth is decoration, not data: try each source briefly, accept only a JPEG, never stop the run.
fetch_earth() {
  local f="$CACHE/earth_bluemarble_5400.jpg" u
  if [[ -s "$f" ]]; then echo "have   earth_bluemarble_5400.jpg"; return 0; fi
  for u in "${EARTH_URLS[@]}"; do
    echo "fetch  $u"
    if curl -fL --connect-timeout 20 --max-time 600 --retry 2 --retry-all-errors -o "$f.part" "$u" \
        && [[ "$(head -c 3 "$f.part" | od -An -tx1 | tr -d ' \n')" == "ffd8ff" ]] \
        && (( $(stat -c %s "$f.part") > 100000 )); then
      mv "$f.part" "$f"; return 0
    fi
    [[ -s "$f.part" ]] && echo "note   got $(stat -c %s "$f.part") bytes of $(file -b "$f.part" 2>/dev/null | cut -c1-60)" >&2
    rm -f "$f.part"; echo "note   that Earth source failed; trying the next" >&2
  done
  echo "warning: no Earth image could be downloaded; the globe draws a plain Earth (rerun later to add it)" >&2
  return 1
}
HAVE_EARTH=0
fetch_earth && HAVE_EARTH=1

ensure_venv

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

EARTH_JSON='null'
if (( HAVE_EARTH )); then
  # Accept only a 2:1 world map at least 2048 px wide (a resized preview or an HTML page is rejected).
  if .venv/bin/python -c 'import sys; from PIL import Image; w, h = Image.open(sys.argv[1]).size; sys.exit(0 if w == 2 * h and w >= 2048 else 1)' \
      "$CACHE/earth_bluemarble_5400.jpg"; then
    check_or_pin "$SRC_LOCK" "$CACHE" earth_bluemarble_5400.jpg
    cp -f "$CACHE/earth_bluemarble_5400.jpg" "$OUT/earth_bluemarble_5400.jpg"
    EARTH_JSON='"earth_bluemarble_5400.jpg"'
  else
    echo "warning: the Earth download is not a 2:1 world map; ignoring it" >&2
    rm -f "$CACHE/earth_bluemarble_5400.jpg"
  fi
fi
[[ "$EARTH_JSON" == 'null' ]] && rm -f "$OUT/earth_bluemarble_5400.jpg"

check_or_pin "$OUT_LOCK" "$APP" "$OUT/lola_16ppd_f16_mips.bin" "$OUT/lola_cap_s_f16_mips.bin" "$OUT/lola_cap_n_f16_mips.bin"

COLORS=""
[[ -s "$OUT/moon_color_8k.jpg" ]] && COLORS='{"file": "moon_color_8k.jpg", "width": 8192}, '
COLORS+='{"file": "moon_color_4k.jpg", "width": 4096}'
cat > "$OUT/textures.json" <<JSON
{"set": "full",
 "moon_color": [$COLORS],
 "heights": {"file": "lola_16ppd_f16_mips.bin", "width": 5760, "height": 2880},
 "caps": {"south": "lola_cap_s_f16_mips.bin", "north": "lola_cap_n_f16_mips.bin", "size": 1536, "lat": 75},
 "earth": $EARTH_JSON}
JSON
echo "done   textures in $OUT"
