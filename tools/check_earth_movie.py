#!/usr/bin/env python3
"""Check the forecast's Earth layer against the production analysis at the same pixels.

``tools/bake_earth_movie.py`` decides "Earth in view" per pixel with its own ray march. The app's
answers (``/api/check``, landing windows) use the production path: an azimuth-binned terrain
horizon from the same 240 m DEM plus SPICE topocentric directions. The forecast must not show a
different answer from the one the panel gives for the same place and time.

Pre-registered (fixed 2026-11-06, before the first run):
  * pixels: 12, seed 20261106. 6 drawn from pixels whose Earth share over the movie is strictly
    between 0 and 1 (where Earth rises and sets; the hard cases), 6 from all on-DEM pixels;
  * for each pixel, the production analysis is run as a custom point (regional DEM, antenna 2 m,
    terrain mode, 120 min step) over the Earth frames' span. It is compared at every Earth frame
    time: ``earth_center_clear`` against the movie bit;
  * PASS: agreement >= 95% over all pixel-frames, and >= 99% over pixel-frames where the
    production margin |earth_margin_deg| >= 0.5 deg (clear cases must agree).

    .venv/bin/python tools/check_earth_movie.py [--movie frontend/app/public/data/shadow_movie]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

R_MOON = 1_737_400.0
SEED = 20261106
N_MIXED, N_ANY = 6, 6
STEP_MIN = 120
LIMIT_ALL, LIMIT_CLEAR, CLEAR_MARGIN_DEG = 0.95, 0.99, 0.5


def _second(utc: str) -> int:
    return round(datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp())


def stereo_to_latlon(x: float, y: float, radius_m: float = R_MOON) -> tuple[float, float]:
    rho = math.hypot(x, y)
    lat = math.degrees(2.0 * math.atan(rho / (2.0 * radius_m))) - 90.0
    lon = math.degrees(math.atan2(x, y)) % 360.0
    return lat, lon


def pick_pixels(share: np.ndarray, valid: np.ndarray, seed: int = SEED) -> list[tuple[int, int, str]]:
    rng = np.random.default_rng(seed)
    mixed = np.argwhere(valid & (share > 0) & (share < 1))
    anyv = np.argwhere(valid)
    out: list[tuple[int, int, str]] = []
    for pool, count, label in ((mixed, N_MIXED, "mixed"), (anyv, N_ANY, "any")):
        if len(pool) == 0:
            continue
        for i in rng.choice(len(pool), size=min(count, len(pool)), replace=False):
            r, c = (int(v) for v in pool[i])
            out.append((r, c, label))
    return out


def score(pairs: list[tuple[bool, bool, float]]) -> dict[str, float | int | bool]:
    """pairs: (movie bit, production clear, production margin deg)."""
    agree_all = [m == p for m, p, _ in pairs]
    clear = [m == p for m, p, margin in pairs if abs(margin) >= CLEAR_MARGIN_DEG]
    a_all = sum(agree_all) / len(agree_all) if agree_all else float("nan")
    a_clear = sum(clear) / len(clear) if clear else float("nan")
    return {"n": len(pairs), "agreement": a_all, "n_clear": len(clear), "agreement_clear": a_clear,
            "pass": bool(agree_all) and a_all >= LIMIT_ALL and (not clear or a_clear >= LIMIT_CLEAR)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--movie", type=Path, default=ROOT / "frontend/app/public/data/shadow_movie")
    args = parser.parse_args()

    from lunar_core import analysis_service, custom_point
    from lunar_core.api_models import AnalysisRequest

    meta = json.loads((args.movie / "earth.json").read_text(encoding="utf-8"))
    n = int(meta["grid"]["size"])
    px, half = float(meta["grid"]["pixel_m"]), float(meta["grid"]["half_width_m"])
    frames = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in meta["frames"]]
    bits = np.unpackbits(np.fromfile(args.movie / "earth.u8", np.uint8))[: len(frames) * n * n]
    stack = bits.reshape(len(frames), n, n).astype(bool)
    share = stack.mean(axis=0)
    valid = np.ones((n, n), bool)  # off-DEM pixels do not occur inside +/-40 km of the regional DEM
    picks = pick_pixels(share, valid)

    start, end = frames[0], frames[-1] + timedelta(minutes=STEP_MIN)
    rows_out, all_pairs = [], []
    for r, c, label in picks:
        x = -half + (c + 0.5) * px
        y = half - (r + 0.5) * px
        lat, lon = stereo_to_latlon(x, y)
        site = custom_point.custom_site(lat, lon)
        pairs: list[tuple[bool, bool, float]] = []
        cursor = start
        while cursor < end:  # the analysis is capped at 60 days per run
            stop = min(end, cursor + timedelta(days=59))
            run = analysis_service.run_analysis(AnalysisRequest(
                site_ids=[site["site_id"]], start_utc=cursor, end_utc=stop, coarse_step_min=STEP_MIN,
                horizon_mode="terrain", sun_observer_height_m=0.0, antenna_height_m=2.0,
            ), extra_sites={site["site_id"]: site})
            series = run["sites"][0]["series"]
            # UTC strings come back from ET and can read 23:59:59.999: match to the nearest second.
            by_time = {_second(s["utc"]): s for s in series}
            for k, t in enumerate(frames):
                s = by_time.get(round(t.timestamp()))
                if s is not None and cursor <= t < stop:
                    pairs.append((bool(stack[k, r, c]), bool(s["earth_center_clear"]), float(s["earth_margin_deg"])))
            cursor = stop
        sc = score(pairs)
        rows_out.append({"row": r, "col": c, "pool": label, "lat": round(lat, 5), "lon": round(lon, 5),
                         "share": float(share[r, c]), **sc})
        all_pairs += pairs
        print(f"  {label:5s} px ({r:3d},{c:3d}) {lat:8.4f} {lon:8.3f}  share {share[r, c]:.2f}  "
              f"n {sc['n']:3d}  agree {sc['agreement']:.1%}  clear-case agree {sc['agreement_clear']:.1%}", flush=True)

    total = score(all_pairs)
    print(f"\nALL: n {total['n']}, agreement {total['agreement']:.2%} (>= {LIMIT_ALL:.0%}); "
          f"clear cases (|margin| >= {CLEAR_MARGIN_DEG} deg) n {total['n_clear']}, {total['agreement_clear']:.2%} "
          f"(>= {LIMIT_CLEAR:.0%})")
    print(f"VERDICT (criteria fixed before the run): {'PASS' if total['pass'] else 'FAIL'}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "data" / "derived" / f"earth_movie_check_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"created_utc": stamp, "total": total, "pixels": rows_out,
                               "criteria": {"all": LIMIT_ALL, "clear": LIMIT_CLEAR, "clear_margin_deg": CLEAR_MARGIN_DEG},
                               "seed": SEED}, indent=2), encoding="utf-8")
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if total["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
