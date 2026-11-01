#!/usr/bin/env python3
"""Convert an SVS CGI Moon Kit LOLA float TIFF (km, relative to 1737.4 km,
equirectangular, centred on 0 deg longitude, row 0 = north) into raw float16
for loadLolaHeights(): row 0 = south, little-endian, no header.

    pip install --break-system-packages tifffile numpy
    cd frontend/app && python3 scripts/lola_to_f16.py ~/Downloads/<4 ppd float TIFF> public/textures/lola_4ppd_f16.bin

Prints width, height, min/max km and SHA-256 so the fetch script can pin them.
"""
import hashlib
import sys

import numpy as np
import tifffile

src, dst = sys.argv[1], sys.argv[2]
km = tifffile.imread(src).astype(np.float32)
if km.ndim != 2 or km.shape[1] != 2 * km.shape[0]:
    sys.exit(f"expected a 2:1 single-band map, got {km.shape}")
if np.nanmax(np.abs(km)) > 25:
    sys.exit("values look like half-metres, not km: use the floating-point TIFF")
out = np.flipud(km).astype("<f2")
err = float(np.max(np.abs(out.astype(np.float32) - np.flipud(km))))
out.tofile(dst)
h, w = km.shape
print(f"{dst}: {w}x{h}, {km.min():.3f}..{km.max():.3f} km, float16 max abs error {err*1000:.1f} m")
print("sha256", hashlib.sha256(open(dst, "rb").read()).hexdigest())
