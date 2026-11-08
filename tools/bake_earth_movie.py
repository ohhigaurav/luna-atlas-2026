#!/usr/bin/env python3
"""Bake the Earth layer of the Moon weather forecast: where a lander can see Earth, frame by frame.

Companion to ``tools/bake_shadow_movie.py``. It reads that tool's ``movie.json`` and uses the
same grid. It makes one Earth frame per ``--every`` Sun frames (default 3: every 6 h at the
default 2 h Sun step).

For every pixel, a ray from the surface point plus the antenna height runs toward the centre of
the Earth. It is marched over the same 240 m regional LOLA DEM, out to 150 km, with the same
sampling as the Sun mask. Differences from the Sun mask:

* **Topocentric direction.** Earth is only 60 Moon radii away, so its direction differs from
  pixel to pixel by up to about 0.27 deg across the Moon. Each ray aims at Earth's position
  vector minus the pixel's position. The Sun mask can use one direction for every pixel because
  the Sun is far enough away.
* **Earth's centre**, not its limb. This is the production analysis's ``earth_center_clear`` rule.
* **Antenna 2 m above the ground**, the landing rule's antenna height (``lunar_core.landing``).

Output, next to the Sun files:
  earth.u8     np.packbits of the visibility mask, n*n bits per Earth frame, row-major
  earth.json   Earth frame times and indices into the Sun frames, method and provenance
  earth_month.png   preview: share of Earth frames with Earth in view (black 0% .. white 100%)

    .venv/bin/python tools/bake_earth_movie.py [--movie frontend/app/public/data/shadow_movie] [--every 3]

Resumable: finished frames are kept in earth_partial_every<N>/ (per --every).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.preview_polar_map import write_png  # noqa: E402
from tools.shadow_match import (  # noqa: E402
    Grid,
    from_stereo,
    load_regional_dem,
    ray_distances,
    to_stereo,
)

R_MOON = 1_737_400.0
ANTENNA_M = 2.0


def earth_mask(dem: Grid, xs: np.ndarray, ys: np.ndarray, earth_m: np.ndarray, antenna_m: float = ANTENNA_M,
               chunk: int = 2048) -> np.ndarray:
    """True where Earth's centre is above the terrain from (x, y) + antenna height.

    ``earth_m`` is Earth's position from the Moon's centre in MOON_ME, metres. A pixel off the DEM
    is False (unknown), never "visible".
    """
    dist = ray_distances()
    out = np.zeros(xs.shape, dtype=bool)
    flat_x, flat_y, flat_out = xs.ravel(), ys.ravel(), out.ravel()
    for a in range(0, flat_x.size, chunk):
        x, y = flat_x[a:a + chunk], flat_y[a:a + chunk]
        h = dem.sample(x, y)
        p = from_stereo(x, y, h + antenna_m)
        d = earth_m[None, :] - p
        d /= np.linalg.norm(d, axis=-1, keepdims=True)
        q = p[:, None, :] + dist[None, :, None] * d[:, None, :]
        qx, qy = to_stereo(q)
        terrain_r = R_MOON + dem.sample(qx, qy)
        blocked = np.any(np.linalg.norm(q, axis=-1) < terrain_r, axis=1)  # NaN: off-DEM never blocks
        flat_out[a:a + chunk] = ~blocked & np.isfinite(h)
    return out


def check_alignment(times: list[datetime], sky_utc: list[str], tol_s: float = 1.0) -> None:
    """Sky sample k must be Earth frame k (to tol_s); the Sun movie must have an even step."""
    if len(sky_utc) < len(times):
        raise SystemExit(f"sky geometry has {len(sky_utc)} samples for {len(times)} Earth frames")
    for k, t in enumerate(times):
        u = datetime.fromisoformat(sky_utc[k].replace("Z", "+00:00"))
        if abs((u - t).total_seconds()) > tol_s:
            raise SystemExit(f"Earth frame {k} at {t:%Y-%m-%d %H:%M:%S} but sky sample at {sky_utc[k]}: "
                             "the Sun movie's frames are not evenly spaced")


def earth_frame_indices(n_sun: int, every: int) -> list[int]:
    if every < 1:
        raise ValueError("every must be >= 1")
    return list(range(0, n_sun, every))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--movie", type=Path, default=ROOT / "frontend/app/public/data/shadow_movie")
    parser.add_argument("--every", type=int, default=3, help="one Earth frame per this many Sun frames")
    args = parser.parse_args()

    from lunar_core import __version__
    from lunar_core.analysis_service import run_sky_geometry
    from lunar_core.api_models import SkyGeometryRequest

    movie = json.loads((args.movie / "movie.json").read_text(encoding="utf-8"))
    grid = movie["grid"]
    n, px, half = int(grid["size"]), float(grid["pixel_m"]), float(grid["half_width_m"])
    centres = -half + (np.arange(n) + 0.5) * px
    xs, ys = np.meshgrid(centres, centres[::-1])  # row 0 = +y, as the Sun frames
    sun_times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in movie["frames"]]
    idx = earth_frame_indices(len(sun_times), args.every)
    times = [sun_times[i] for i in idx]
    step_min = int(round((sun_times[1] - sun_times[0]).total_seconds() / 60)) * args.every if len(sun_times) > 1 else 60

    part = args.movie / f"earth_partial_every{args.every}"  # resume only with the same frame spacing
    part.mkdir(parents=True, exist_ok=True)
    print(f"{len(times)} Earth frames (every {args.every} Sun frames), {n}x{n} px; loading DEM ...", flush=True)
    dem = load_regional_dem(half + 150_000.0 + 2 * px)
    sky = run_sky_geometry(SkyGeometryRequest(start_utc=times[0], end_utc=times[-1] + timedelta(minutes=step_min),
                                              step_min=max(1, step_min)))
    s_utc = sky["series"]["utc"]
    earth_unit = np.asarray(sky["series"]["earth"]["unit"], float)
    earth_km = np.asarray(sky["series"]["earth"]["distance_km"], float)
    # The sky grid starts at the first Earth frame with the Earth-frame step, so sample k is frame k.
    check_alignment(times, s_utc)

    started, done = time.monotonic(), 0
    todo = [k for k in range(len(times)) if not (part / f"{k:04d}.npz").is_file()]
    for k in todo:
        mask = earth_mask(dem, xs, ys, earth_unit[k] * earth_km[k] * 1000.0)
        np.savez_compressed(part / f"{k:04d}.npz", earth=np.packbits(mask))
        done += 1
        rate = (time.monotonic() - started) / done
        print(f"  earth {k + 1}/{len(times)} {times[k]:%Y-%m-%d %H:%M} UTC: Earth in view from {mask.mean():.0%}, "
              f"~{(len(todo) - done) * rate / 60:.0f} min left", flush=True)

    packed = [np.load(part / f"{k:04d}.npz")["earth"] for k in range(len(times))]
    (args.movie / "earth.u8").write_bytes(np.concatenate(packed).tobytes())
    share = np.mean([np.unpackbits(p)[: n * n].reshape(n, n) for p in packed], axis=0)
    write_png(args.movie / "earth_month.png", np.stack([(share * 255).astype(np.uint8)] * 3, axis=-1))
    (args.movie / "earth.json").write_text(json.dumps({
        "schema_version": "1.0", "kind": "south_pole_earth_visibility_movie", "software_version": __version__,
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "frames": [t.astimezone(UTC).isoformat().replace("+00:00", "Z") for t in times],
        "sun_frame_index": idx,
        "grid": grid,
        "files": {"earth_bits": "earth.u8", "preview": "earth_month.png"},
        "encoding": "np.packbits of the mask, n*n bits per Earth frame, row-major; 1 = Earth's centre in view",
        "method": ("Ray from the surface + 2 m antenna toward Earth's centre (topocentric: Earth position minus the "
                   "pixel position), marched over the 240 m regional LOLA DEM to 150 km; the analysis's "
                   "earth_center_clear rule"),
        "antenna_height_m": ANTENNA_M,
        "kernel_manifest_sha256": sky["provenance"]["kernel_manifest_sha256"],
        "limits": ("240 m terrain; terrain beyond 150 km ignored; geometric line of sight only, not a radio link "
                   "budget. Earth frames are every 6 h by default; between frames, hold the previous frame."),
        "month_share": {"never": float((share == 0).mean()), "always": float((share == 1).mean())},
    }, indent=2), encoding="utf-8")
    print(f"wrote {args.movie}/earth.u8, earth.json, earth_month.png; never in view {float((share == 0).mean()):.1%}, "
          f"always {float((share == 1).mean()):.1%} of the area")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
