#!/usr/bin/env python3
"""Convert an SVS CGI Moon Kit LOLA elevation TIFF into raw float16 for loadLolaHeights().

Input (svs.gsfc.nasa.gov/4720, equirectangular, centred on 0 deg longitude, row 0 = north):
  * ldem_<N>.tif       float32, km relative to 1737.4 km
  * ldem_<N>_uint.tif  uint16, half-metres offset by +20000 (i.e. relative to 1727.4 km)
Output: little-endian float16 km relative to 1737.4 km, row 0 = SOUTH, no header.
With --mips, the full mip chain (box-filtered, each level floor-halved down to 1x1) follows
level 0 back to back, matching mipChain() in src/scene/lunarMaterial.ts.

    python3 scripts/lola_to_f16.py ldem_16.tif public/textures/lola_16ppd_f16_mips.bin --mips \
        --caps public/textures/lola_cap --cap-size 1536 --cap-lat 75

--caps also writes <prefix>_s_f16_mips.bin and <prefix>_n_f16_mips.bin: the same heights
resampled (bilinear) onto polar stereographic grids poleward of --cap-lat, where an
equirectangular map stretches each pixel across a wide range of longitude and its relief
shading smears into radial wedges. Grid axes: +x along MOON_ME +X (0 deg E), +y along MOON_ME +Y
(90 deg E); rho = 2 tan(colatitude / 2) in Moon radii; row 0 = -y; the grid spans +-rho(cap-lat).

Prints size, range, float16 error and SHA-256 so the fetch script can pin them.
"""
import argparse
import hashlib
import sys

import numpy as np
import tifffile

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--mips", action="store_true", help="append the full mip chain")
ap.add_argument("--caps", help="also write polar stereographic caps to <prefix>_{s,n}_f16_mips.bin")
ap.add_argument("--cap-size", type=int, default=1536)
ap.add_argument("--cap-lat", type=float, default=75.0)
a = ap.parse_args()


def mip_levels(level):
    """Full box-filtered chain, each level floor-halved down to 1x1 (matches mipChain() in TS)."""
    out = [level]
    while level.shape[0] > 1 or level.shape[1] > 1:
        h, w = level.shape
        h2, w2 = max(1, h // 2), max(1, w // 2)
        cropped = level[: h2 * (2 if h > 1 else 1), : w2 * (2 if w > 1 else 1)]
        level = cropped.reshape(h2, cropped.shape[0] // h2, w2, cropped.shape[1] // w2).mean(axis=(1, 3))
        out.append(level)
    return out


def write_f16(path, levels):
    with open(path, "wb") as f:
        for lv in levels:
            f.write(lv.astype("<f2").tobytes())
    return hashlib.sha256(open(path, "rb").read()).hexdigest()

raw = tifffile.imread(a.src)
if raw.ndim != 2 or raw.shape[1] != 2 * raw.shape[0]:
    sys.exit(f"expected a 2:1 single-band map, got {raw.shape}")
if raw.dtype == np.uint16:
    km = (raw.astype(np.float64) - 20000.0) / 2000.0   # SVS: half-metres + 20000 -> km vs 1737.4 km
else:
    km = raw.astype(np.float64)
    if np.nanmax(np.abs(km)) > 25:
        sys.exit("float values look like metres or half-metres, not km")
if not (-12.0 < np.nanmin(km) and np.nanmax(km) < 12.0):
    sys.exit(f"range {np.nanmin(km):.3f}..{np.nanmax(km):.3f} km is not lunar relief")

level = np.flipud(km)                                    # row 0 = south (GL texture origin)
levels = mip_levels(level) if a.mips else [level]
digest = write_f16(a.dst, levels)

err = float(np.max(np.abs(levels[0].astype("<f2").astype(np.float64) - levels[0])))
h, w = km.shape
print(f"{a.dst}: {w}x{h}{f' + {len(levels) - 1} mip levels' if a.mips else ''}, "
      f"{km.min():.3f}..{km.max():.3f} km, float16 max abs error {err * 1000:.1f} m")
print("sha256", digest)

if a.caps:
    H, W = km.shape                                       # source rows north-first, lon -180..180
    rho_max = 2.0 * np.tan(np.radians(90.0 - a.cap_lat) / 2.0)
    n = a.cap_size
    axis = (np.arange(n) + 0.5) / n * 2.0 * rho_max - rho_max
    px, py = np.meshgrid(axis, axis)                      # row index = y (row 0 = -y)
    rho = np.hypot(px, py)
    colat = 2.0 * np.arctan(rho / 2.0)
    lon = np.degrees(np.arctan2(py, px))                  # east-positive, -180..180
    col = (lon + 180.0) / 360.0 * W - 0.5
    for tag, sign in (("s", -1.0), ("n", 1.0)):
        lat = sign * (90.0 - np.degrees(colat))
        row = (90.0 - lat) / 180.0 * H - 0.5
        r0 = np.clip(np.floor(row).astype(int), 0, H - 1); r1 = np.clip(r0 + 1, 0, H - 1)
        c0 = np.floor(col).astype(int); c1 = c0 + 1
        fr = np.clip(row - np.floor(row), 0, 1); fc = col - np.floor(col)
        c0 %= W; c1 %= W
        cap = ((km[r0, c0] * (1 - fc) + km[r0, c1] * fc) * (1 - fr) + (km[r1, c0] * (1 - fc) + km[r1, c1] * fc) * fr)
        path = f"{a.caps}_{tag}_f16_mips.bin"
        d = write_f16(path, mip_levels(cap))
        print(f"{path}: {n}x{n} polar stereographic, |lat| >= {a.cap_lat} (rho_max {rho_max:.6f}), "
              f"{cap.min():.3f}..{cap.max():.3f} km")
        print("sha256", d)
