#!/usr/bin/env python3
"""Many-point check of modelled sunlight against LROC's observed illumination map.

Why: the six-site comparison (validation/evidence/wac_illumination_2026-11-01.md) could not score
either lit site, and one site agreeing after a cause was chosen can be coincidence. This tool
compares the model with the WAC map at many 100 m pixels inside the two 5 m PGDA tiles.

Method
------
1. Pixels. For each 5 m tile (LOLA Site 001 and Site 004), candidate WAC pixels are those whose
   whole 100 m square lies inside the tile and whose centre is within 3 km of the site point.
   They are split into five strata by observed value (0-5, 5-20, 20-35, 35-50, >=50 %) and up
   to N per stratum (default 10) are drawn with a fixed seed, so dark, partly lit and well lit
   ground are all tested. The draw depends only on the map, never on model output.
2. Model per pixel. An n x n grid of points inside the pixel (default 3 x 3, 33 m apart), each
   with its own production terrain horizon (``build_horizon_from_dem_assets``, production
   defaults) at observer height 0 m (the camera sees the ground). The pixel's model value is the
   mean of its points.
3. Sun. One ``/api/sky-geometry`` track for the WAC period (2010-02-15 to 2011-02-05, 30 min),
   turned into each point's local azimuth/elevation. "Lit" uses the analysis definition: Sun
   upper limb above the terrain horizon (Sun-centre fraction reported too).

Gate before scoring (fixed 2026-11-01, before any run): the fast path at the published Site 001
and Site 004 points must reproduce the production analysis values in the 0 m WAC report within
0.3 percentage points. If not, the tool stops and nothing is scored.

Acceptance criterion (fixed 2026-11-01, before any run), over all sampled pixels pooled:
  * at least 30 pixels scored, and
  * median(model - WAC) within +/-5 percentage points, and
  * at least 70 % of pixels with |model - WAC| <= 10 percentage points, and
  * Spearman rank correlation >= 0.80.
Per-tile and per-stratum results are reported but do not change the verdict. A FAIL is
recorded as a FAIL; the thresholds are not changed after seeing results.

Known differences that remain: the WAC "lit" threshold is photometric, not a Sun-limb geometry;
WAC image timing is irregular (LROC also publishes a time-weighted map; pass it with --map); the
model's 3 x 3 points approximate a pixel average; DEM errors.

The run is resumable: finished points are appended to a checkpoint file, so Ctrl+C and rerun.

    .venv/bin/python tools/wac_manypoint.py [--per-stratum 10] [--subgrid 3] [--map PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.compare_wac_illumination import (  # noqa: E402
    DEFAULT_MAP,
    MOON_RADIUS_M,
    WAC_END,
    WAC_START,
    check_crs,
    stereographic_south,
)

SEED = 20261101
STRATA = ((0.0, 5.0), (5.0, 20.0), (20.0, 35.0), (35.0, 50.0), (50.0, 101.0))
RADIUS_M = 3000.0
PIXEL_M = 100.0
STEP_MIN = 30
OBSERVER_HEIGHT_M = 0.0
SUN_RADIUS_M = 695_700_000.0
GATE_PP = 0.3
MIN_PIXELS = 30
MEDIAN_LIMIT_PP = 5.0
WITHIN_PP = 10.0
WITHIN_SHARE = 0.70
SPEARMAN_MIN = 0.80
TILES = {
    "reference-lola-site-001": "pgda78-site01-surface",
    "reference-lola-site-004": "pgda78-site04-surface",
}


# --- geometry helpers (pure; unit-tested) ----------------------------------------------------

def inverse_stereographic_south(x_m: float, y_m: float, radius_m: float = MOON_RADIUS_M) -> tuple[float, float]:
    """Inverse of ``stereographic_south``: latitude, east longitude [0, 360)."""
    rho = math.hypot(x_m, y_m)
    lat = math.degrees(2.0 * math.atan(rho / (2.0 * radius_m)) - math.pi / 2.0)
    lon = math.degrees(math.atan2(x_m, y_m)) % 360.0 if rho > 0 else 0.0
    return lat, lon


def subpixel_offsets(n: int, pixel_m: float = PIXEL_M) -> list[float]:
    """Centres of an n x n split of a pixel, as offsets from the pixel centre (one axis)."""
    if n < 1:
        raise ValueError("subgrid must be >= 1")
    return [((i + 0.5) / n - 0.5) * pixel_m for i in range(n)]


def stratum_of(value: float) -> int | None:
    for index, (lo, hi) in enumerate(STRATA):
        if lo <= value < hi:
            return index
    return None


def select_pixels(
    candidates: Sequence[tuple[int, int, float]], per_stratum: int, seed: int = SEED,
) -> list[tuple[int, int, float, int]]:
    """Deterministic stratified draw. ``candidates`` are (row, col, wac_pct)."""
    rng = random.Random(seed)
    chosen: list[tuple[int, int, float, int]] = []
    for index in range(len(STRATA)):
        pool = sorted((r, c, v) for r, c, v in candidates if stratum_of(v) == index)
        picked = rng.sample(pool, min(per_stratum, len(pool)))
        chosen.extend((r, c, v, index) for r, c, v in sorted(picked))
    return chosen


def lit_fractions(
    sun_unit: Any, sun_distance_km: Any, lat_deg: float, lon_deg: float, observer_radius_m: float,
    horizon_az_deg: Any, horizon_el_rad: Any,
) -> tuple[float, float]:
    """Upper-limb and centre lit fractions over a Moon-centred Sun track (numpy arrays)."""
    import numpy as np

    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    up = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    east = np.array([-math.sin(lon), math.cos(lon), 0.0])
    north = np.array([-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)])
    rel = sun_unit * (sun_distance_km[:, None] * 1000.0) - up * observer_radius_m
    rng = np.linalg.norm(rel, axis=1)
    elevation = np.arcsin(np.clip(rel @ up / rng, -1.0, 1.0))
    azimuth = np.degrees(np.arctan2(rel @ east, rel @ north)) % 360.0
    horizon = np.interp(azimuth, horizon_az_deg, horizon_el_rad, period=360.0)
    semidiameter = np.arcsin(SUN_RADIUS_M / rng)
    limb = float(np.mean(elevation + semidiameter - horizon > 0.0))
    centre = float(np.mean(elevation - horizon > 0.0))
    return limb, centre


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2.0 + 1.0
            i = j + 1
        return out

    ra, rb = ranks(a), ranks(b)
    n = len(ra)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va > 0 and vb > 0 else float("nan")


def score(pixels: Sequence[dict[str, Any]]) -> dict[str, Any]:
    diffs = sorted(p["model_limb_pct"] - p["wac_pct"] for p in pixels)
    n = len(diffs)
    if n == 0:
        return {"n": 0, "verdict": "INSUFFICIENT"}
    median = diffs[n // 2] if n % 2 else (diffs[n // 2 - 1] + diffs[n // 2]) / 2.0
    within = sum(1 for d in diffs if abs(d) <= WITHIN_PP) / n
    rho = spearman([p["model_limb_pct"] for p in pixels], [p["wac_pct"] for p in pixels]) if n > 2 else float("nan")
    checks = {
        "median_diff_pp": {"value": median, "pass": abs(median) <= MEDIAN_LIMIT_PP},
        "share_within_10pp": {"value": within, "pass": within >= WITHIN_SHARE},
        "spearman": {"value": rho, "pass": rho >= SPEARMAN_MIN},
    }
    if n < MIN_PIXELS:
        verdict = "INSUFFICIENT"
    else:
        verdict = "PASS" if all(c["pass"] for c in checks.values()) else "FAIL"
    return {"n": n, "checks": checks, "mean_diff_pp": sum(diffs) / n, "verdict": verdict}


# --- run -------------------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _latest_production_report() -> Path | None:
    found = sorted((ROOT / "data/derived").glob("wac_comparison_terrain_h0m_*.json"))
    return found[-1] if found else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--per-stratum", type=int, default=10)
    parser.add_argument("--subgrid", type=int, default=3)
    parser.add_argument("--production-report", type=Path, default=None,
                        help="0 m terrain report from compare_wac_illumination.py (default: newest)")
    args = parser.parse_args()

    import numpy as np
    import rasterio
    from lunar_core.analysis_service import DEM_MANIFEST, PROJECT_ROOT, run_sky_geometry
    from lunar_core.api_models import SkyGeometryRequest
    from lunar_core.references import load_reference_catalogue
    from lunar_core.terrain import (
        HORIZON_ALGORITHM_VERSION,
        _source_lunar_crs,
        build_horizon_from_dem_assets,
        load_dem_manifest,
    )
    from pyproj import Transformer

    production_path = args.production_report or _latest_production_report()
    if production_path is None or not production_path.is_file():
        raise SystemExit("need the 0 m production report (run compare_wac_illumination.py --observer-height 0 first)")
    production = json.loads(production_path.read_text(encoding="utf-8"))
    if float(production.get("observer_height_m", -1)) != OBSERVER_HEIGHT_M or production.get("mode") != "terrain":
        raise SystemExit(f"{production_path.name} is not a terrain run at 0 m")
    production_limb = {row["site_id"]: row.get("model_limb_pct") for row in production["sites"]}

    refs = {s.site_id: s for s in load_reference_catalogue().sites}
    assets = {a.asset_id: a for a in load_dem_manifest(DEM_MANIFEST).assets}

    print(f"Sun track {WAC_START.date()} -> {WAC_END.date()}, {STEP_MIN} min ...", flush=True)
    sky = run_sky_geometry(SkyGeometryRequest(start_utc=WAC_START, end_utc=WAC_END, step_min=STEP_MIN))
    sun_unit = np.asarray(sky["series"]["sun"]["unit"], dtype=float)
    sun_dist = np.asarray(sky["series"]["sun"]["distance_km"], dtype=float)
    radius_m = float(sky["moon_reference_radius_m"])

    def point_fraction(site_id: str, lat: float, lon: float) -> dict[str, Any]:
        horizon, ground, _meta = build_horizon_from_dem_assets(
            site_id, lat, lon, observer_height_m=OBSERVER_HEIGHT_M, reference_radius_m=radius_m,
            manifest_path=DEM_MANIFEST, project_root=PROJECT_ROOT,
        )
        if any(b.coverage_status != "complete" or b.elevation_rad is None for b in horizon.bins):
            raise SystemExit(f"incomplete horizon at {lat:.6f}, {lon:.6f}; terrain coverage gap")
        az = np.array([b.azimuth_deg for b in horizon.bins])
        el = np.array([b.elevation_rad for b in horizon.bins])
        limb, centre = lit_fractions(sun_unit, sun_dist, lat, lon, radius_m + ground + OBSERVER_HEIGHT_M, az, el)
        return {"lat": lat, "lon": lon, "ground_m": ground, "limb_pct": 100 * limb, "centre_pct": 100 * centre}

    # Gate: reproduce production at the published points.
    gate: dict[str, Any] = {}
    for site_id in TILES:
        ref = refs[site_id]
        t0 = time.monotonic()
        fast = point_fraction(site_id, ref.latitude_deg, ref.longitude_deg)
        seconds_per_point = time.monotonic() - t0
        prod = production_limb.get(site_id)
        ok = prod is not None and abs(fast["limb_pct"] - float(prod)) <= GATE_PP
        gate[site_id] = {"fast_limb_pct": fast["limb_pct"], "production_limb_pct": prod, "pass": ok}
        print(f"gate {site_id}: fast {fast['limb_pct']:.2f} % vs production {prod} % -> {'PASS' if ok else 'FAIL'} "
              f"({seconds_per_point:.1f} s/point)", flush=True)
    if not all(item["pass"] for item in gate.values()):
        print("Gate failed: the fast path does not reproduce the production analysis. Nothing scored.")
        return 2

    with rasterio.open(args.map) as ds:
        check_crs(ds.crs.to_wkt())
        if abs(ds.transform.a - PIXEL_M) > 1e-6 or abs(ds.transform.e + PIXEL_M) > 1e-6:
            raise SystemExit(f"{args.map.name}: expected {PIXEL_M:g} m pixels, got {ds.transform.a}, {ds.transform.e}")
        values = ds.read(1, masked=True)
        transform = ds.transform
    data = np.ma.filled(values.astype(float), np.nan)
    offsets = subpixel_offsets(args.subgrid)

    settings = {
        "map_sha256": _sha256(args.map), "kernel_manifest_sha256": sky["provenance"]["kernel_manifest_sha256"],
        "horizon_algorithm": HORIZON_ALGORITHM_VERSION, "subgrid": args.subgrid, "per_stratum": args.per_stratum,
        "seed": SEED, "radius_m": RADIUS_M, "step_min": STEP_MIN, "observer_height_m": OBSERVER_HEIGHT_M,
        "tile_sha256": {sid: assets[aid].sha256 for sid, aid in TILES.items()},
    }
    key = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:16]
    checkpoint = ROOT / "data/derived" / f"wac_manypoint_{key}.jsonl"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    done: dict[tuple[str, int, int, int, int], dict[str, Any]] = {}
    if checkpoint.is_file():
        for line in checkpoint.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            done[(rec["site_id"], rec["row"], rec["col"], rec["i"], rec["j"])] = rec

    plan: list[dict[str, Any]] = []
    for site_id, asset_id in TILES.items():
        ref = refs[site_id]
        sx, sy = stereographic_south(ref.latitude_deg, ref.longitude_deg)
        with rasterio.open(PROJECT_ROOT / assets[asset_id].relative_path) as tile:
            # Tile bounds are used in the WAC map's x/y, so the tile must share that projection.
            tx, ty = Transformer.from_crs(_source_lunar_crs(radius_m), tile.crs, always_xy=True).transform(
                ref.longitude_deg, ref.latitude_deg)
            if math.hypot(tx - sx, ty - sy) > 1.0:
                raise SystemExit(f"{asset_id} projection differs from the WAC map's by {math.hypot(tx - sx, ty - sy):.1f} m")
            left, bottom, right, top = tile.bounds
        half = PIXEL_M / 2.0
        candidates: list[tuple[int, int, float]] = []
        for row in range(data.shape[0]):
            y = transform.f + (row + 0.5) * transform.e
            if not (bottom + half <= y <= top - half) or abs(y - sy) > RADIUS_M:
                continue
            for col in range(data.shape[1]):
                x = transform.c + (col + 0.5) * transform.a
                if not (left + half <= x <= right - half) or math.hypot(x - sx, y - sy) > RADIUS_M:
                    continue
                value = float(data[row, col])
                if math.isfinite(value) and value >= 0.0:
                    candidates.append((row, col, value))
        chosen = select_pixels(candidates, args.per_stratum)
        print(f"{site_id}: {len(candidates)} candidate pixels, {len(chosen)} drawn "
              f"({', '.join(str(sum(1 for c in chosen if c[3] == k)) for k in range(len(STRATA)))} per stratum)")
        for row, col, value, stratum in chosen:
            plan.append({"site_id": site_id, "row": row, "col": col, "wac_pct": value, "stratum": stratum,
                         "x": transform.c + (col + 0.5) * transform.a, "y": transform.f + (row + 0.5) * transform.e})

    total = len(plan) * args.subgrid ** 2
    remaining = total - sum(1 for p in plan for i in range(args.subgrid) for j in range(args.subgrid)
                            if (p["site_id"], p["row"], p["col"], i, j) in done)
    print(f"{len(plan)} pixels x {args.subgrid ** 2} points = {total} horizons; {remaining} to compute "
          f"(~{remaining * seconds_per_point / 60:.0f} min at the gate's pace). Checkpoint: {checkpoint.relative_to(ROOT)}",
          flush=True)

    started = time.monotonic()
    computed = 0
    with checkpoint.open("a", encoding="utf-8") as sink:
        for p in plan:
            for i, dx in enumerate(offsets):
                for j, dy in enumerate(offsets):
                    k = (p["site_id"], p["row"], p["col"], i, j)
                    if k in done:
                        continue
                    lat, lon = inverse_stereographic_south(p["x"] + dx, p["y"] - dy)
                    rec = {"site_id": p["site_id"], "row": p["row"], "col": p["col"], "i": i, "j": j,
                           **point_fraction(p["site_id"], lat, lon)}
                    sink.write(json.dumps(rec) + "\n")
                    sink.flush()
                    done[k] = rec
                    computed += 1
                    if computed % 25 == 0:
                        rate = (time.monotonic() - started) / computed
                        print(f"  {computed}/{remaining} points, ~{(remaining - computed) * rate / 60:.0f} min left", flush=True)

    pixels: list[dict[str, Any]] = []
    for p in plan:
        recs = [done[(p["site_id"], p["row"], p["col"], i, j)] for i in range(args.subgrid) for j in range(args.subgrid)]
        limbs = [r["limb_pct"] for r in recs]
        pixels.append({**p, "model_limb_pct": sum(limbs) / len(limbs),
                       "model_centre_pct": sum(r["centre_pct"] for r in recs) / len(recs),
                       "model_point_min_pct": min(limbs), "model_point_max_pct": max(limbs)})

    pooled = score(pixels)
    per_tile = {sid: score([p for p in pixels if p["site_id"] == sid]) for sid in TILES}
    per_stratum = {f"{lo:g}-{hi:g}": score([p for p in pixels if p["stratum"] == k]) for k, (lo, hi) in enumerate(STRATA)}

    print(f"\n{'group':28s} {'n':>4s} {'median d':>9s} {'mean d':>8s} {'|d|<=10':>8s} {'spearman':>9s}")
    for name, s in [("ALL", pooled), *per_tile.items(), *((f"WAC {k} %", v) for k, v in per_stratum.items())]:
        if not s["n"]:
            print(f"{name:28s} {0:4d}")
            continue
        c = s["checks"]
        print(f"{name:28s} {s['n']:4d} {c['median_diff_pp']['value']:+9.1f} {s['mean_diff_pp']:+8.1f} "
              f"{100 * c['share_within_10pp']['value']:7.0f}% {c['spearman']['value']:9.2f}")
    print(f"\nVERDICT (pooled, criterion fixed before the run): {pooled['verdict']}")

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "created_utc": stamp, "settings": settings, "checkpoint": str(checkpoint.relative_to(ROOT)),
        "period": [WAC_START.isoformat(), WAC_END.isoformat()],
        "criterion": {"min_pixels": MIN_PIXELS, "median_limit_pp": MEDIAN_LIMIT_PP, "within_pp": WITHIN_PP,
                      "within_share": WITHIN_SHARE, "spearman_min": SPEARMAN_MIN, "gate_pp": GATE_PP},
        "production_report": str(production_path), "gate": gate,
        "pooled": pooled, "per_tile": per_tile, "per_stratum": per_stratum,
        "sky_geometry_provenance": sky["provenance"], "pixels": pixels,
    }
    out = ROOT / "data/derived" / f"wac_manypoint_{stamp}.json"
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"report: {out.relative_to(ROOT)}")
    return 0 if pooled["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
