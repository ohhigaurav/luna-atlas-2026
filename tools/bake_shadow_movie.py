#!/usr/bin/env python3
"""Bake the "Moon weather forecast": the south pole's light and shadow, frame by frame, for any dates.

Each frame is rendered with the same method that matched real LRO WAC photos in
``tools/shadow_match.py`` (5 of 6 frames passed the pre-registered test on 2026-11-04):

  * the Sun's direction at the frame time from the production SPICE path (``run_sky_geometry``);
  * for every pixel, a ray toward the Sun's upper limb over the regional 240 m LOLA DEM decides
    lit or shadowed;
  * lit pixels are shaded by the cosine of the Sun's angle to the local surface normal, so slopes
    facing the Sun glow and slopes facing away dim, like a photograph. This shading is for
    display; the science is the lit/shadow mask.

Output (default frontend/app/public/data/shadow_movie/):
  movie.json       grid, frame times, provenance
  frames.u8        uint8 brightness, layout [frame][row][col], row 0 = +y (0 E side)
  lit.u8           1 bit per pixel packed (np.packbits) per frame: the lit mask itself
  png/frame_NNNN.png   quick-look frames; movie.mp4 if ffmpeg is installed

    .venv/bin/python tools/bake_shadow_movie.py [--start 2027-01-01T00:00:00Z] [--days 30] [--step-h 2]
                                                [--half-km 40] [--px-m 250]

Resumable: finished frames are kept in png/ and frames_partial/; rerun the same command to continue.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.preview_polar_map import write_png  # noqa: E402
from tools.shadow_match import Grid, from_stereo, lit_mask, load_regional_dem  # noqa: E402


def surface_normals(dem: Grid, xs: np.ndarray, ys: np.ndarray, d: float) -> np.ndarray:
    """Unit surface normals (MOON_ME) from DEM heights at +/- d metres in stereographic x and y."""
    def p(dx: float, dy: float) -> np.ndarray:
        x, y = xs + dx, ys + dy
        return from_stereo(x, y, dem.sample(x, y))

    tx = p(d, 0) - p(-d, 0)
    ty = p(0, d) - p(0, -d)
    n = np.cross(tx, ty)
    up = from_stereo(xs, ys, np.zeros_like(xs))
    n = np.where((np.sum(n * up, axis=-1) < 0)[..., None], -n, n)  # point away from the Moon's centre
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def shade(lit: np.ndarray, normals: np.ndarray, sun_unit: np.ndarray, gamma: float = 0.7) -> np.ndarray:
    """uint8 brightness: cos(incidence) on lit pixels, 0 in shadow; gamma for display."""
    cos_i = np.clip(np.sum(normals * sun_unit, axis=-1), 0.0, 1.0)
    value = np.where(lit, cos_i, 0.0)
    peak = max(float(value.max()), 1e-6)
    return np.clip(255.0 * (value / peak) ** gamma, 0, 255).astype(np.uint8)


def frame_times(start: datetime, days: float, step_h: float) -> list[datetime]:
    n = int(round(days * 24 / step_h))
    return [start + timedelta(hours=step_h * k) for k in range(n)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2027-01-01T00:00:00Z")
    parser.add_argument("--days", type=float, default=30.0)
    parser.add_argument("--step-h", type=float, default=2.0)
    parser.add_argument("--half-km", type=float, default=40.0)
    parser.add_argument("--px-m", type=float, default=250.0)
    parser.add_argument("--out", type=Path, default=ROOT / "frontend/app/public/data/shadow_movie")
    args = parser.parse_args()

    from lunar_core import __version__
    from lunar_core.analysis_service import run_sky_geometry
    from lunar_core.api_models import SkyGeometryRequest

    start = datetime.fromisoformat(args.start.replace("Z", "+00:00")).astimezone(UTC)
    times = frame_times(start, args.days, args.step_h)
    half = args.half_km * 1000.0
    n = int(round(2 * half / args.px_m))
    centres = -half + (np.arange(n) + 0.5) * args.px_m
    xs, ys = np.meshgrid(centres, centres[::-1])  # row 0 = +y
    out, png_dir, part_dir = args.out, args.out / "png", args.out / "frames_partial"
    for d in (png_dir, part_dir):
        d.mkdir(parents=True, exist_ok=True)

    print(f"{len(times)} frames, {n}x{n} px at {args.px_m:g} m, +/-{args.half_km:g} km; loading DEM ...", flush=True)
    dem = load_regional_dem(half + 150_000.0 + 2 * args.px_m)
    normals = surface_normals(dem, xs, ys, args.px_m / 2.0)
    print(f"Sun track for {len(times)} frames ...", flush=True)
    sky = run_sky_geometry(SkyGeometryRequest(start_utc=times[0], end_utc=times[-1] + timedelta(hours=args.step_h),
                                              step_min=max(1, int(round(args.step_h * 60)))))
    suns = np.asarray(sky["series"]["sun"]["unit"], float)
    radii = np.radians(np.asarray(sky["series"]["sun"]["angular_radius_deg"], float))

    started, done_now = time.monotonic(), 0
    todo = [k for k in range(len(times)) if not (part_dir / f"{k:04d}.npz").is_file()]
    for k in todo:
        lit = lit_mask(dem, xs, ys, suns[k], float(radii[k]), 0.0)
        img = shade(lit, normals, suns[k])
        np.savez_compressed(part_dir / f"{k:04d}.npz", img=img, lit=np.packbits(lit))
        write_png(png_dir / f"frame_{k:04d}.png", np.stack([img] * 3, axis=-1))
        done_now += 1
        rate = (time.monotonic() - started) / done_now
        print(f"  frame {k + 1}/{len(times)} {times[k]:%Y-%m-%d %H:%M} UTC: {lit.mean():.0%} lit, "
              f"~{(len(todo) - done_now) * rate / 60:.0f} min left", flush=True)

    frames = np.empty((len(times), n, n), np.uint8)
    lits = []
    for k in range(len(times)):
        z = np.load(part_dir / f"{k:04d}.npz")
        frames[k] = z["img"]
        lits.append(z["lit"])
    (out / "frames.u8").write_bytes(frames.tobytes())
    (out / "lit.u8").write_bytes(np.concatenate(lits).tobytes())
    (out / "movie.json").write_text(json.dumps({
        "schema_version": "1.0", "kind": "south_pole_shadow_movie", "software_version": __version__,
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "frames": [t.isoformat().replace("+00:00", "Z") for t in times],
        "grid": {"size": n, "pixel_m": args.px_m, "half_width_m": half, "row_0": "+y (toward 0 E)",
                 "projection": "south polar stereographic, R=1737400 m, x = rho*sin(lon), y = rho*cos(lon)"},
        "files": {"brightness": "frames.u8", "lit_bits": "lit.u8"},
        "encoding": {"brightness": "uint8 [frame][row][col]; cos(incidence) on lit pixels, gamma 0.7, display only",
                     "lit_bits": "np.packbits of the lit mask, n*n bits per frame, row-major"},
        "method": ("Sun upper limb vs terrain by ray march over the 240 m regional LOLA DEM; same method as "
                   "tools/shadow_match.py, which passed 5/6 LRO WAC photos (validation/evidence/shadow_match_2026-11-04.md)"),
        "kernel_manifest_sha256": sky["provenance"]["kernel_manifest_sha256"],
        "limits": "240 m terrain: features smaller than ~0.5 km are not resolved; observer at the surface.",
    }, indent=2), encoding="utf-8")
    print(f"wrote {out}/frames.u8 ({frames.nbytes / 1e6:.1f} MB) and movie.json")
    if shutil.which("ffmpeg"):
        fps = 24
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(png_dir / "frame_%04d.png"),
                        "-vf", "scale=1024:1024:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                        "-pix_fmt", "yuv420p", str(out / "movie.mp4")], check=True)
        print(f"wrote {out}/movie.mp4 ({len(times) / fps:.0f} s at {fps} fps)")
    else:
        print("ffmpeg not found: PNG frames are in png/ (install ffmpeg for movie.mp4)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
