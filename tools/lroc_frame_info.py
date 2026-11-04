#!/usr/bin/env python3
"""Inspect one LROC WAC south-pole movie frame (8-bit GeoTIFF) before using it for a shadow match.

Prints: size, projection check, nodata tag, value histogram near zero, footprint (non-zero area), and
how many zero pixels sit inside the footprint (deep shadow) vs outside it (no image). Writes a PNG of
the central +/-HALF km (default 60 km), north (0 E) up, for a visual check.

    .venv/bin/python tools/lroc_frame_info.py data/reference/lroc_movie/WAC_MOVIE_S20090920T0850.TIF [--half-km 60]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.compare_wac_illumination import check_crs  # noqa: E402
from tools.preview_polar_map import write_png  # noqa: E402


def footprint(nonzero: np.ndarray) -> np.ndarray:
    """Pixels inside the image swath: rows/cols between the first and last non-zero pixel of each row,
    so zeros surrounded by imaged ground count as shadow, not as "no image"."""
    inside = np.zeros_like(nonzero, dtype=bool)
    for r in range(nonzero.shape[0]):
        cols = np.flatnonzero(nonzero[r])
        if cols.size:
            inside[r, cols[0]:cols[-1] + 1] = True
    cols_mask = np.zeros_like(inside)
    for c in range(nonzero.shape[1]):
        rows = np.flatnonzero(nonzero[:, c])
        if rows.size:
            cols_mask[rows[0]:rows[-1] + 1, c] = True
    return inside & cols_mask


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tif", type=Path)
    parser.add_argument("--half-km", type=float, default=60.0)
    args = parser.parse_args()
    import rasterio

    with rasterio.open(args.tif) as ds:
        check_crs(ds.crs.to_wkt())
        a = ds.read(1)
        t = ds.transform
        print(f"{args.tif.name}: {ds.width}x{ds.height} {ds.dtypes[0]}, {t.a:g} m px, nodata tag={ds.nodata}, "
              f"projection OK, origin ({t.c:.0f}, {t.f:.0f})")
    hist = np.bincount(a.ravel(), minlength=256)
    print("pixels with value 0..10:", hist[:11].tolist())
    print(f"value percentiles of non-zero pixels (1, 5, 50, 95, 99): "
          f"{np.percentile(a[a > 0], [1, 5, 50, 95, 99]).round(1).tolist() if (a > 0).any() else 'none'}")
    inside = footprint(a > 0)
    zeros = a == 0
    print(f"footprint covers {inside.mean() * 100:.1f}% of the frame; zeros inside it (shadow candidates): "
          f"{(zeros & inside).sum() / max(inside.sum(), 1) * 100:.1f}% of footprint; zeros outside: {(zeros & ~inside).mean() * 100:.1f}% of frame")

    half = int(args.half_km * 1000 / t.a)
    cr, cc = int((0 - t.f) / t.e), int((0 - t.c) / t.a)  # pixel of the pole
    crop = a[cr - half:cr + half, cc - half:cc + half]
    ins = inside[cr - half:cr + half, cc - half:cc + half]
    step = max(1, crop.shape[0] // 600)
    crop, ins = crop[::step, ::step], ins[::step, ::step]
    rgb = np.stack([crop] * 3, axis=-1).astype(float)
    rgb[~ins] = (60, 0, 60)  # purple = outside the image swath (no data)
    out = args.tif.with_suffix(".center.png")
    write_png(out, rgb)
    print(f"wrote {out} (+/-{args.half_km:g} km around the pole, 0 E up, purple = not imaged)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
