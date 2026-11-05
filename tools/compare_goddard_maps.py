#!/usr/bin/env python3
"""Gate E: our Sun and Earth visibility vs NASA Goddard's published south-pole maps (PGDA product 69).

References (Mazarico et al. 2011, Icarus 211; PGDA "Lunar Polar Illumination", 85-90 S, 60 m/px):
  * AVGVISIB_85S_060M_201608.TIF        average fraction of the solar disc visible (0-1), 18.6 years hourly
  * AVGVISIB_85S_060M_201608_EARTH.TIF  same for Earth's disc
  * LPSR_85S_060M_201608.TIF            permanent shadow (1) or not (0)
Labels: DN * 0.00004 for the visibility maps (DN 0 = permanent shadow); PSR = DN * 0.000025 + 0.5.

Our side: for each test pixel centre, the production terrain horizon (``build_horizon_from_dem_assets``,
regional 240 m DEM, observer at the surface, 0 m) and one hourly Sun/Earth track from
``/api/sky-geometry`` covering 18.6 years from 2009-07-13. Per hour, the visible fraction of each disc
is the circular-segment area above the local horizon (straight-horizon approximation across the disc);
the average over all hours is compared with the map.

Pre-registered (fixed 2026-11-05, before any run):
  * draw: pixels within 60 km of the pole whose 3x3 neighbourhood (180 m) varies by at most 0.10 in
    the Sun map (our DEM is 240 m; we do not score features it cannot resolve); five strata by the
    Sun map value (0-0.05, 0.05-0.2, 0.2-0.4, 0.4-0.6, >=0.6); 12 per stratum; seed 20261105;
  * Sun PASS:   |median(ours - map)| <= 0.05, >= 70% of points within 0.10, Spearman >= 0.80;
  * Earth PASS: the same three thresholds on the Earth map, over the same points;
  * PSR PASS:   >= 90% agreement between "map says permanent shadow" and "our average Sun visibility
    is below 0.001", over the same points;
  * the gate passes only if Sun, Earth and PSR all pass. Reported, not scored: the same at 2 m.

Differences we know about: their DEM (LOLA, 2016 product, 60 m) vs ours (240 m regional); their exact
18.6-year span is not stated in the label (START/STOP give the LOLA data span), ours starts 2009-07-13;
straight-horizon disc fractions.

    .venv/bin/python tools/compare_goddard_maps.py [--dir data/reference/pgda69]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.bake_polar_map import margins  # noqa: E402
from tools.compare_wac_illumination import stereographic_south  # noqa: E402
from tools.wac_manypoint import inverse_stereographic_south, spearman  # noqa: E402

SEED = 20261105
STRATA = ((0.0, 0.05), (0.05, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.01))
PER_STRATUM = 12
RADIUS_KM = 60.0
MAX_SPREAD = 0.10
MEDIAN_LIMIT = 0.05
WITHIN = 0.10
WITHIN_SHARE = 0.70
SPEARMAN_MIN = 0.80
PSR_AGREEMENT = 0.90
PSR_SUN_MAX = 0.001
YEARS = 18.6
START = datetime(2009, 7, 13, tzinfo=UTC)
SUN_RADIUS_M = 695_700_000.0
EARTH_RADIUS_M = 6_378_136.6
FILES = {"sun": "AVGVISIB_85S_060M_201608.TIF", "earth": "AVGVISIB_85S_060M_201608_EARTH.TIF",
         "psr": "LPSR_85S_060M_201608.TIF"}


def disc_fraction(margin_rad: np.ndarray, semidiameter_rad: np.ndarray) -> np.ndarray:
    """Visible fraction of a disc whose centre is ``margin`` above a straight horizon line."""
    h = np.clip(margin_rad / semidiameter_rad, -1.0, 1.0)
    return 1.0 - (np.arccos(h) - h * np.sqrt(1.0 - h * h)) / np.pi


def physical(values: np.ndarray, kind: str) -> np.ndarray:
    """Map DN (int) or already-scaled float rasters to 0-1 per the PDS labels."""
    v = values.astype(float)
    if np.issubdtype(values.dtype, np.integer):
        return v * 0.000025 + 0.5 if kind == "psr" else v * 0.00004
    return v


def draw(sun: np.ndarray, row_y: np.ndarray, col_x: np.ndarray, seed: int = SEED) -> list[tuple[int, int, int]]:
    """Stratified draw of (row, col, stratum) from pixels near the pole with a smooth 3x3 neighbourhood.

    ``row_y`` / ``col_x`` are the stereographic y of each row and x of each column (m)."""
    h, w = sun.shape
    pad = np.pad(sun, 1, mode="edge")
    stack = np.stack([pad[r:r + h, c:c + w] for r in range(3) for c in range(3)])
    spread = stack.max(0) - stack.min(0)
    xx, yy = np.meshgrid(col_x, row_y)
    near = np.hypot(xx, yy) <= RADIUS_KM * 1000.0
    ok = near & (spread <= MAX_SPREAD) & np.isfinite(sun)
    rng = random.Random(seed)
    out: list[tuple[int, int, int]] = []
    for k, (lo, hi) in enumerate(STRATA):
        rows, cols = np.nonzero(ok & (sun >= lo) & (sun < hi))
        pool = sorted(zip(rows.tolist(), cols.tolist(), strict=True))
        out += [(r, c, k) for r, c in sorted(rng.sample(pool, min(PER_STRATUM, len(pool))))]
    return out


def judge(ours: list[float], ref: list[float]) -> dict[str, Any]:
    d = sorted(o - r for o, r in zip(ours, ref, strict=True))
    n = len(d)
    median = d[n // 2] if n % 2 else (d[n // 2 - 1] + d[n // 2]) / 2
    within = sum(abs(x) <= WITHIN for x in d) / n
    rho = spearman(ours, ref)
    return {"n": n, "median_diff": median, "mean_diff": sum(d) / n, "share_within": within, "spearman": rho,
            "pass": abs(median) <= MEDIAN_LIMIT and within >= WITHIN_SHARE and rho >= SPEARMAN_MIN}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, default=ROOT / "data/reference/pgda69")
    args = parser.parse_args()
    import rasterio
    from lunar_core.analysis_service import DEM_MANIFEST, PROJECT_ROOT, run_sky_geometry
    from lunar_core.api_models import SkyGeometryRequest
    from lunar_core.terrain import _source_lunar_crs, build_horizon_from_dem_assets
    from pyproj import Transformer

    maps: dict[str, np.ndarray] = {}
    transform = None
    for kind, name in FILES.items():
        with rasterio.open(args.dir / name) as ds:
            tx, ty = Transformer.from_crs(_source_lunar_crs(1_737_400.0), ds.crs, always_xy=True).transform(129.8, -89.6)
            ex, ey = stereographic_south(-89.6, 129.8)
            if math.hypot(tx - ex, ty - ey) > 1.0:
                raise SystemExit(f"{name}: projection differs from ours by {math.hypot(tx - ex, ty - ey):.1f} m")
            # Read only the +/-(RADIUS + 1 km) square around the pole: the full maps are ~5000^2 pixels.
            from rasterio.windows import Window
            half = (RADIUS_KM + 1.0) * 1000.0
            c0 = int(math.floor((-half - ds.transform.c) / ds.transform.a))
            r0 = int(math.floor((ds.transform.f - half) / -ds.transform.e))
            size = int(math.ceil(2 * half / ds.transform.a)) + 1
            win = Window(c0, r0, size, size)
            maps[kind] = physical(ds.read(1, window=win), kind).astype(np.float32)
            transform = transform or ds.window_transform(win)
            print(f"{name}: {ds.width}x{ds.height} {ds.dtypes[0]}, {ds.res[0]:g} m px, range "
                  f"{np.nanmin(maps[kind]):.3f}..{np.nanmax(maps[kind]):.3f}", flush=True)
    t = transform
    rows_y = t.f + (np.arange(maps["sun"].shape[0]) + 0.5) * t.e
    cols_x = t.c + (np.arange(maps["sun"].shape[1]) + 0.5) * t.a
    picks = draw(maps["sun"], rows_y, cols_x)
    print(f"{len(picks)} points drawn ({', '.join(str(sum(p[2] == k for p in picks)) for k in range(len(STRATA)))} per stratum)")

    print(f"Sun/Earth track: {YEARS} years hourly from {START.date()} ...", flush=True)
    end = START + timedelta(days=YEARS * 365.25)
    sun_u, sun_d, earth_u, earth_d = [], [], [], []
    cursor = START
    while cursor < end:
        stop = min(end, cursor + timedelta(days=360))
        s = run_sky_geometry(SkyGeometryRequest(start_utc=cursor, end_utc=stop, step_min=60))["series"]
        k = slice(0, -1) if stop < end else slice(None)  # drop the duplicated chunk boundary
        sun_u += s["sun"]["unit"][k]; sun_d += s["sun"]["distance_km"][k]  # noqa: E702
        earth_u += s["earth"]["unit"][k]; earth_d += s["earth"]["distance_km"][k]  # noqa: E702
        cursor = stop
    su, sd_km = np.asarray(sun_u), np.asarray(sun_d)
    eu, ed_km = np.asarray(earth_u), np.asarray(earth_d)
    print(f"  {len(su)} hourly samples", flush=True)

    rows: list[dict[str, Any]] = []
    started = time.monotonic()
    for i, (r, c, stratum) in enumerate(picks, 1):
        x, y = float(cols_x[c]), float(rows_y[r])
        lat, lon = inverse_stereographic_south(x, y)
        rec: dict[str, Any] = {"row": r, "col": c, "stratum": stratum, "lat": lat, "lon": lon,
                               "map_sun": float(maps["sun"][r, c]), "map_earth": float(maps["earth"][r, c]),
                               "map_psr": bool(maps["psr"][r, c] > 0.5)}
        for height in (0.0, 2.0):
            hz, ground, _ = build_horizon_from_dem_assets("polar-map-grid", lat, lon, observer_height_m=height,
                                                          reference_radius_m=1_737_400.0, manifest_path=DEM_MANIFEST,
                                                          project_root=PROJECT_ROOT)
            az = np.array([b.azimuth_deg for b in hz.bins])
            el = np.array([b.elevation_rad if b.elevation_rad is not None else np.nan for b in hz.bins])
            if not np.isfinite(el).all():
                rec[f"h{height:g}"] = None
                continue
            r_obs = 1_737_400.0 + ground + height
            ms = margins(su, sd_km, lat, lon, r_obs, az, el, add_semidiameter=False)
            me = margins(eu, ed_km, lat, lon, r_obs, az, el, add_semidiameter=False)
            sun_sd = np.arcsin(SUN_RADIUS_M / (sd_km * 1000.0))
            earth_sd = np.arcsin(EARTH_RADIUS_M / (ed_km * 1000.0))
            rec[f"h{height:g}"] = {"sun": float(disc_fraction(ms, sun_sd).mean()),
                                   "earth": float(disc_fraction(me, earth_sd).mean()), "ground_m": ground}
        rows.append(rec)
        print(f"  {i}/{len(picks)} map sun {rec['map_sun']:.3f} ours {rec['h0']['sun'] if rec['h0'] else float('nan'):.3f} | "
              f"map earth {rec['map_earth']:.3f} ours {rec['h0']['earth'] if rec['h0'] else float('nan'):.3f} "
              f"(~{(len(picks) - i) * (time.monotonic() - started) / i / 60:.0f} min left)", flush=True)

    scored = [r for r in rows if r["h0"]]
    results: dict[str, Any] = {}
    for height in ("h0", "h2"):
        ok = [r for r in scored if r[height]]
        sun = judge([r[height]["sun"] for r in ok], [r["map_sun"] for r in ok])
        earth = judge([r[height]["earth"] for r in ok], [r["map_earth"] for r in ok])
        psr_agree = sum((r["map_psr"]) == (r[height]["sun"] < PSR_SUN_MAX) for r in ok) / len(ok)
        results[height] = {"sun": sun, "earth": earth, "psr_agreement": psr_agree,
                           "psr_pass": psr_agree >= PSR_AGREEMENT}
    verdict = results["h0"]["sun"]["pass"] and results["h0"]["earth"]["pass"] and results["h0"]["psr_pass"]

    print(f"\n{'':10s} {'n':>3s} {'median d':>9s} {'mean d':>8s} {'|d|<=0.1':>9s} {'spearman':>9s}")
    for height in ("h0", "h2"):
        for what in ("sun", "earth"):
            j = results[height][what]
            print(f"{what + ' ' + height:10s} {j['n']:3d} {j['median_diff']:+9.3f} {j['mean_diff']:+8.3f} "
                  f"{j['share_within']:8.0%} {j['spearman']:9.2f}  {'PASS' if j['pass'] else 'FAIL'}")
        print(f"{'psr ' + height:10s} agreement {results[height]['psr_agreement']:.0%}  "
              f"{'PASS' if results[height]['psr_pass'] else 'FAIL'}")
    print(f"\nVERDICT (0 m, criterion fixed before the run): {'PASS' if verdict else 'FAIL'}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "data/derived" / f"goddard_comparison_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"created_utc": stamp, "verdict": verdict, "results": results, "points": rows,
                               "track": {"start": START.isoformat(), "years": YEARS, "samples": len(su)}},
                              indent=2), encoding="utf-8")
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
