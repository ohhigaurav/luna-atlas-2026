#!/usr/bin/env python3
"""Find the highest point of the 240 m regional LOLA DEM near a coordinate, then compare it with that coordinate.

Why: the Malapert Massif reference point taken from NASA's image page (85.99 S, 357.07 E) gets
Earth 0% for November 2026 on our terrain. Malapert is known for Earth visibility from its summit.
A point at the mirrored longitude (2.93 E) is 280 m higher and gets Earth 76% (`malapert.log`,
6 Nov). Rather than guess where the summit is, this reads it off the DEM.

    .venv/bin/python tools/find_summit.py [--lat -85.99] [--lon 357.07] [--radius-km 15]
                                          [--at 2026-11-06T00:00:00Z] [--days 30]

It prints the DEM's highest point within the radius, the five highest local spots more than 1 km
apart, and a side-by-side compare (Sun, Earth, next events) of the given point and the summit.
Nothing in the catalogue changes. A "summit" reference point, if wanted, would be added by hand
with this DEM as its source.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

R_MOON = 1_737_400.0


def to_stereo(lat_deg: float, lon_deg: float, radius_m: float = R_MOON) -> tuple[float, float]:
    rho = 2.0 * radius_m * math.tan(math.radians(90.0 + lat_deg) / 2.0)
    return rho * math.sin(math.radians(lon_deg)), rho * math.cos(math.radians(lon_deg))


def from_stereo(x: float, y: float, radius_m: float = R_MOON) -> tuple[float, float]:
    rho = math.hypot(x, y)
    return math.degrees(2.0 * math.atan(rho / (2.0 * radius_m))) - 90.0, math.degrees(math.atan2(x, y)) % 360.0


def top_spots(xs: np.ndarray, ys: np.ndarray, h: np.ndarray, count: int = 5, min_sep_m: float = 1000.0) -> list[tuple[float, float, float]]:
    """Highest points, greedily, each at least min_sep_m from those already taken."""
    order = np.argsort(np.where(np.isfinite(h), h, -np.inf).ravel())[::-1]
    out: list[tuple[float, float, float]] = []
    for k in order:
        if not np.isfinite(h.ravel()[k]):
            break
        x, y = float(xs.ravel()[k]), float(ys.ravel()[k])
        if all(math.hypot(x - a, y - b) >= min_sep_m for a, b, _ in out):
            out.append((x, y, float(h.ravel()[k])))
            if len(out) == count:
                break
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lat", type=float, default=-85.99)
    parser.add_argument("--lon", type=float, default=357.07)
    parser.add_argument("--radius-km", type=float, default=15.0)
    parser.add_argument("--at", default="2026-11-06T00:00:00Z")
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    from tools.shadow_match import load_regional_dem

    cx, cy = to_stereo(args.lat, args.lon)
    r = args.radius_km * 1000.0
    dem = load_regional_dem(math.hypot(cx, cy) + r + 2_000.0)
    step = dem.px
    offs = np.arange(-r, r + step / 2, step)
    xs, ys = np.meshgrid(cx + offs, cy + offs)
    inside = np.hypot(xs - cx, ys - cy) <= r
    h = np.where(inside, dem.sample(xs, ys), np.nan)
    here = float(dem.sample(np.array(cx), np.array(cy)))
    spots = top_spots(xs, ys, h)
    print(f"Given point {args.lat:.4f}, {args.lon % 360:.4f} E: DEM height {here:.1f} m")
    print(f"Highest points within {args.radius_km:g} km (240 m DEM, at least 1 km apart):")
    for x, y, z in spots:
        lat, lon = from_stereo(x, y)
        d = math.hypot(x - cx, y - cy) / 1000.0
        print(f"  {lat:9.4f} {lon:9.4f} E  {z:7.1f} m  ({d:.1f} km from the given point)")

    from lunar_core.api_models import CompareRequest
    from lunar_core.compare import run_compare

    sx, sy, _ = spots[0]
    slat, slon = from_stereo(sx, sy)
    res = run_compare(CompareRequest(places=[{"latitude_deg": args.lat, "longitude_deg": args.lon % 360},
                                             {"latitude_deg": round(slat, 5), "longitude_deg": round(slon, 5)}],
                                     at_utc=args.at, days=args.days))
    print(f"\nCompare at {res['at_utc'][:16]} over {args.days} d:")
    for row, label in zip(res["rows"], ("given point", "DEM summit"), strict=True):
        p, sn, en = row["period"], row["sun_next"], row["earth_next"]
        print(f"  {label:11s} {row['site']['name']}: ground {row['terrain']['ground_elevation_m']:.0f} m | "
              f"sun {p['sunlit_percent']:.0f}%  earth {p['earth_percent']:.0f}%  both {p['both_percent']:.0f}% | "
              f"Earth horizon now {row['now']['earth']['horizon_deg']:+.2f}° | {sn['event']} / {en['event']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
