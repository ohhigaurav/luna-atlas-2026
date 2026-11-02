#!/usr/bin/env python3
"""Render the baked polar map as PNGs (no plotting libraries needed).

For each month: sunlight % as brightness (black = never lit, white = always), with Earth-in-view as a
blue tint, upscaled with nearest-neighbour so grid points stay visible. Also writes a 12-month strip.

    .venv/bin/python tools/preview_polar_map.py [--dir frontend/app/public/data/polar_map] [--scale 8]
"""
from __future__ import annotations

import argparse
import json
import struct
import zlib
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def write_png(path: Path, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[r].astype(np.uint8).tobytes() for r in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def colourise(sun_pct: np.ndarray, earth_pct: np.ndarray, missing: np.ndarray) -> np.ndarray:
    s = np.clip(sun_pct / 100.0, 0, 1) ** 0.6          # gamma: make partly lit ground readable
    e = np.clip(earth_pct / 100.0, 0, 1)
    rgb = np.stack([255 * s * (1 - 0.35 * e), 235 * s * (1 - 0.15 * e) + 10 * e, 200 * s + 55 * e], axis=-1)
    rgb[missing] = (90, 0, 0)
    return rgb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=ROOT / "frontend/app/public/data/polar_map")
    parser.add_argument("--scale", type=int, default=8)
    args = parser.parse_args()
    meta = json.loads((args.dir / "map.json").read_text(encoding="utf-8"))
    n, days = meta["grid"]["size"], meta["days"]
    sun = np.frombuffer((args.dir / "sun_daily_pct.u8").read_bytes(), np.uint8).reshape(days, n, n)
    earth = np.frombuffer((args.dir / "earth_daily_pct.u8").read_bytes(), np.uint8).reshape(days, n, n)
    missing = sun[0] == 255
    year = int(meta["first_day_utc"][:4])
    tiles = []
    for month in range(1, 13):
        a = (date(year, month, 1) - date(year, 1, 1)).days
        b = (date(year + (month == 12), month % 12 + 1, 1) - date(year, 1, 1)).days
        img = colourise(sun[a:b].astype(float).mean(0), earth[a:b].astype(float).mean(0), missing)
        img = img.repeat(args.scale, 0).repeat(args.scale, 1)
        write_png(args.dir / f"preview_{year}_{month:02d}.png", img)
        tiles.append(img)
    pad = np.zeros((tiles[0].shape[0], 4, 3))
    strip = np.concatenate([np.concatenate([t, pad], 1) for t in tiles[:6]], 1)
    strip2 = np.concatenate([np.concatenate([t, pad], 1) for t in tiles[6:]], 1)
    write_png(args.dir / f"preview_{year}_months.png", np.concatenate([strip, np.zeros((4, strip.shape[1], 3)), strip2], 0))
    print(f"wrote 13 PNGs in {args.dir} (Jan-Jun top row, Jul-Dec bottom; north edge = 0 E side)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
