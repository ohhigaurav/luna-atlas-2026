#!/usr/bin/env bash
# Download the six pre-registered LROC WAC south-pole movie frames used by tools/shadow_match.py
# (8-bit map-projected GeoTIFFs, ~35 MB each). Safe to re-run: finished files are skipped,
# partial files are resumed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/data/reference/lroc_movie"
BASE="https://pds.lroc.im-ldi.com/data/LRO-L-LROC-5-RDR-V1.0/LROLRC_2001/EXTRAS/BROWSE/WAC_POLE/WAC_POLE_MOVIE_SOUTH"
mkdir -p "$OUT"
for f in WAC_MOVIE_S20090920T0850 WAC_MOVIE_S20090924T0707 WAC_MOVIE_S20090928T0001 \
         WAC_MOVIE_S20091002T0015 WAC_MOVIE_S20091010T0042 WAC_MOVIE_S20091015T0124; do
  if [[ -s "$OUT/$f.TIF" && ! -e "$OUT/$f.TIF.part" ]]; then echo "have   $f.TIF"; continue; fi
  echo "fetch  $f.TIF"
  curl -fL --retry 3 -C - -o "$OUT/$f.TIF.part" "$BASE/$f.TIF"
  mv "$OUT/$f.TIF.part" "$OUT/$f.TIF"
done
echo "done: $(command ls "$OUT"/*.TIF | wc -l) frames in $OUT"
