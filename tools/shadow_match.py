#!/usr/bin/env python3
"""Shadow match: do our computed shadows line up with real LRO photographs of the south pole?

For each LROC WAC south-pole movie frame (map-projected 8-bit GeoTIFF, 100 m/pixel, polar
stereographic like our map), this tool:

1. computes the Sun's direction at the frame's time (file name, to the minute) with the production
   SPICE path (``run_sky_geometry``);
2. renders our shadow mask on the frame's own 100 m pixel grid around the pole: from each pixel, a
   ray toward the Sun's upper limb is marched over the regional 240 m LOLA DEM (the same DEM and
   spherical geometry as the production horizon code); a pixel is lit if no terrain blocks it;
3. classifies the photo: inside the imaged strip, a pixel is lit if its value is at or above the
   Otsu threshold of that frame's in-strip values (computed automatically, never tuned by hand);
4. compares them outside a 200 m band around our modelled shadow edges (the DEM is 240 m, so edges
   cannot be placed better than that), and writes a side-by-side picture.

Pre-registered (fixed 2026-11-04, before any run):
  * frames: WAC_MOVIE_S20090920T0850, S20090924T0707, S20090928T0001, S20091002T0015,
    S20091010T0042, S20091015T0124 (spread over a lunar month, so the Sun comes from different
    directions). A frame is scored only if the imaged strip covers at least 50% of the scoring disc;
  * scoring disc: within 15 km of the pole (Shackleton, its rim, Sites 001 and 004); observer at the
    surface (0 m), as the camera sees it;
  * a frame PASSES if agreement >= 85% and shadow IoU (intersection over union of the shadow
    classes) >= 0.70. The test PASSES if at least two thirds of the scored frames pass;
  * gate before scoring: at 4 reference points, lit/dark from this ray march must agree with the
    production horizon code (``build_horizon_from_dem_assets``, same DEM) wherever the production
    margin exceeds 0.2 deg. Otherwise the tool stops and nothing is scored.

    .venv/bin/python tools/shadow_match.py data/reference/lroc_movie/WAC_MOVIE_S*.TIF
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from tools.compare_wac_illumination import check_crs, stereographic_south  # noqa: E402
from tools.lroc_frame_info import footprint  # noqa: E402
from tools.preview_polar_map import write_png  # noqa: E402

R_MOON = 1_737_400.0
SUN_RADIUS_M = 695_700_000.0
FRAMES = ["WAC_MOVIE_S20090920T0850", "WAC_MOVIE_S20090924T0707", "WAC_MOVIE_S20090928T0001",
          "WAC_MOVIE_S20091002T0015", "WAC_MOVIE_S20091010T0042", "WAC_MOVIE_S20091015T0124"]
DISC_KM = 15.0
OBSERVER_M = 0.0
EDGE_BAND_M = 200.0
MIN_COVERAGE = 0.5
PASS_AGREEMENT = 0.85
PASS_IOU = 0.70
GATE_MARGIN_DEG = 0.2
REGIONAL_ASSET = "pgda90-60s-240m-regional"


# --- pure geometry (unit-tested) ---------------------------------------------------------------

def frame_time(name: str) -> datetime:
    m = re.search(r"S(\d{8})T(\d{4})", name)
    if not m:
        raise ValueError(f"no time in frame name {name!r}")
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").replace(tzinfo=UTC)


def to_stereo(p: np.ndarray, radius_m: float = R_MOON) -> tuple[np.ndarray, np.ndarray]:
    """Cartesian MOON_ME points (..., 3) -> south polar stereographic x, y (m)."""
    r = np.linalg.norm(p, axis=-1)
    lat = np.arcsin(np.clip(p[..., 2] / r, -1.0, 1.0))
    lon = np.arctan2(p[..., 1], p[..., 0])
    rho = 2.0 * radius_m * np.tan(np.pi / 4.0 + lat / 2.0)
    return rho * np.sin(lon), rho * np.cos(lon)


def from_stereo(x: np.ndarray, y: np.ndarray, height_m: np.ndarray, radius_m: float = R_MOON) -> np.ndarray:
    """Stereographic x, y plus height above the sphere -> Cartesian MOON_ME (..., 3)."""
    rho = np.hypot(x, y)
    lat = 2.0 * np.arctan(rho / (2.0 * radius_m)) - np.pi / 2.0
    lon = np.arctan2(x, y)
    r = radius_m + height_m
    return np.stack([r * np.cos(lat) * np.cos(lon), r * np.cos(lat) * np.sin(lon), r * np.sin(lat)], axis=-1)


class Grid:
    """A north-up raster in stereographic metres: value at pixel centres, bilinear in between."""

    def __init__(self, values: np.ndarray, x0: float, y0: float, px: float) -> None:
        self.v, self.x0, self.y0, self.px = values, x0, y0, px  # x0, y0 = outer corner of pixel (0, 0)

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        c = (x - self.x0) / self.px - 0.5
        r = (self.y0 - y) / self.px - 0.5
        h, w = self.v.shape
        c0, r0 = np.floor(c).astype(int), np.floor(r).astype(int)
        fc, fr = c - c0, r - r0
        ok = (c0 >= 0) & (r0 >= 0) & (c0 + 1 < w) & (r0 + 1 < h)
        c0, r0 = np.clip(c0, 0, w - 2), np.clip(r0, 0, h - 2)
        v = (self.v[r0, c0] * (1 - fc) * (1 - fr) + self.v[r0, c0 + 1] * fc * (1 - fr)
             + self.v[r0 + 1, c0] * (1 - fc) * fr + self.v[r0 + 1, c0 + 1] * fc * fr)
        return np.where(ok, v, np.nan)


def ray_distances(max_m: float = 150_000.0) -> np.ndarray:
    """Dense near the observer (the DEM decides near-field shading), coarser far away."""
    near = np.arange(20.0, 2_000.0, 20.0)
    mid = np.arange(2_000.0, 20_000.0, 120.0)
    far = np.arange(20_000.0, max_m + 1.0, 240.0)
    return np.concatenate([near, mid, far])


def upper_limb_direction(sun_unit: np.ndarray, up: np.ndarray, semidiameter_rad: float) -> np.ndarray:
    """Direction to the Sun's upper limb: the centre direction tilted toward local up by the semidiameter."""
    perp = up - np.sum(up * sun_unit, axis=-1, keepdims=True) * sun_unit
    norm = np.linalg.norm(perp, axis=-1, keepdims=True)
    perp = np.where(norm > 1e-12, perp / np.maximum(norm, 1e-12), 0.0)
    d = sun_unit + math.tan(semidiameter_rad) * perp
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def lit_mask(dem: Grid, xs: np.ndarray, ys: np.ndarray, sun_unit: np.ndarray, semidiameter_rad: float,
             observer_m: float = 0.0, chunk: int = 2048) -> np.ndarray:
    """True where the Sun's upper limb is visible from the surface point (x, y) + observer height."""
    dist = ray_distances()
    out = np.zeros(xs.shape, dtype=bool)
    flat_x, flat_y, flat_out = xs.ravel(), ys.ravel(), out.ravel()
    for a in range(0, flat_x.size, chunk):
        x, y = flat_x[a:a + chunk], flat_y[a:a + chunk]
        h = dem.sample(x, y)
        p = from_stereo(x, y, h + observer_m)
        up = p / np.linalg.norm(p, axis=-1, keepdims=True)
        d = upper_limb_direction(np.broadcast_to(sun_unit, p.shape), up, semidiameter_rad)
        q = p[:, None, :] + dist[None, :, None] * d[:, None, :]          # (n, k, 3) points along the ray
        qx, qy = to_stereo(q)
        terrain_r = R_MOON + dem.sample(qx, qy)
        blocked = np.any(np.linalg.norm(q, axis=-1) < terrain_r, axis=1)   # NaN compares False: off-DEM never blocks
        flat_out[a:a + chunk] = ~blocked & np.isfinite(h)
    return out


def otsu(values: np.ndarray) -> int:
    hist = np.bincount(values.astype(np.int64), minlength=256).astype(float)
    total = hist.sum()
    if total == 0:
        raise ValueError("no values")
    w0 = np.cumsum(hist)
    m = np.cumsum(hist * np.arange(256))
    mt = m[-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mt * w0 / total - m) ** 2 / (w0 * (total - w0))
    between[~np.isfinite(between)] = -1
    return int(np.argmax(between)) + 1  # lit if value >= threshold


def edge_band(mask: np.ndarray, pixels: int) -> np.ndarray:
    """Pixels within ``pixels`` (Chebyshev) of a lit/dark boundary of ``mask``."""
    band = np.zeros_like(mask, dtype=bool)
    m = mask.astype(np.int8)
    edge = np.zeros_like(band)
    edge[:-1, :] |= m[:-1, :] != m[1:, :]
    edge[1:, :] |= m[:-1, :] != m[1:, :]
    edge[:, :-1] |= m[:, :-1] != m[:, 1:]
    edge[:, 1:] |= m[:, :-1] != m[:, 1:]
    for dr in range(-pixels, pixels + 1):
        for dc in range(-pixels, pixels + 1):
            band |= np.roll(np.roll(edge, dr, 0), dc, 1)
    return band


def score(model_lit: np.ndarray, photo_lit: np.ndarray, scored: np.ndarray) -> dict[str, float]:
    m, p = model_lit[scored], photo_lit[scored]
    n = m.size
    if n == 0:
        return {"pixels": 0}
    shadow_m, shadow_p = ~m, ~p
    union = (shadow_m | shadow_p).sum()
    return {"pixels": int(n), "agreement": float((m == p).mean()),
            "shadow_iou": float((shadow_m & shadow_p).sum() / union) if union else 1.0,
            "model_lit_photo_dark": float((m & ~p).mean()), "model_dark_photo_lit": float((~m & p).mean())}


# --- run -----------------------------------------------------------------------------------------

def load_regional_dem(half_m: float) -> Grid:
    import rasterio
    from lunar_core.analysis_service import DEM_MANIFEST, PROJECT_ROOT
    from lunar_core.terrain import _physical_grid_m, _source_lunar_crs, load_dem_manifest
    from pyproj import Transformer

    asset = next(a for a in load_dem_manifest(DEM_MANIFEST).assets if a.asset_id == REGIONAL_ASSET)
    with rasterio.open(PROJECT_ROOT / asset.relative_path) as ds:
        tx, ty = Transformer.from_crs(_source_lunar_crs(R_MOON), ds.crs, always_xy=True).transform(129.8, -89.6)
        ex, ey = stereographic_south(-89.6, 129.8)
        if math.hypot(tx - ex, ty - ey) > 1.0:
            raise SystemExit("regional DEM projection differs from the photo/map projection")
        t = ds.transform
        c0 = int(math.floor((-half_m - t.c) / t.a))
        r0 = int(math.floor((t.f - half_m) / -t.e))
        size = int(math.ceil(2 * half_m / t.a)) + 2
        from rasterio.windows import Window
        raw = ds.read(1, window=Window(c0, r0, size, size), masked=True)
        values = _physical_grid_m(ds, raw, asset.elevation_units)
        return Grid(values, t.c + c0 * t.a, t.f + r0 * t.e, t.a)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("frames", nargs="+", type=Path)
    args = parser.parse_args()
    import rasterio
    from lunar_core.analysis_service import DEM_MANIFEST, PROJECT_ROOT, run_sky_geometry
    from lunar_core.api_models import SkyGeometryRequest
    from lunar_core.terrain import build_horizon_from_dem_assets

    names = {p.stem.split(".")[0]: p for p in args.frames}
    unexpected = sorted(set(names) - set(FRAMES))
    if unexpected:
        raise SystemExit(f"not in the pre-registered frame set: {unexpected}")
    print("loading regional DEM (+/-170 km) ...", flush=True)
    dem = load_regional_dem(170_000.0)

    results: list[dict[str, Any]] = []
    out_dir = ROOT / "data/derived/shadow_match"
    out_dir.mkdir(parents=True, exist_ok=True)
    gate_done = False
    for name in FRAMES:
        if name not in names:
            print(f"{name}: not downloaded, skipped")
            continue
        when = frame_time(name)
        sky = run_sky_geometry(SkyGeometryRequest(start_utc=when, end_utc=when + timedelta(minutes=1), step_min=1))
        sun = np.asarray(sky["series"]["sun"]["unit"][0], float)
        sd = math.radians(sky["series"]["sun"]["angular_radius_deg"][0])

        if not gate_done:  # production-horizon consistency gate, at the first frame's Sun
            for lat, lon, label in ((-89.45, 222.69, "Site 001"), (-89.78, 204.27, "Site 004"),
                                    (-89.60, 129.80, "Shackleton floor"), (-89.30, 150.0, "rim area")):
                hz, ground, _ = build_horizon_from_dem_assets("polar-map-grid", lat, lon, observer_height_m=OBSERVER_M,
                                                              reference_radius_m=R_MOON, manifest_path=DEM_MANIFEST,
                                                              project_root=PROJECT_ROOT)
                x, y = stereographic_south(lat, lon)
                p = from_stereo(np.array([x]), np.array([y]), np.array([ground + OBSERVER_M]))[0]
                up = p / np.linalg.norm(p)
                east = np.array([-math.sin(math.radians(lon)), math.cos(math.radians(lon)), 0.0])
                north = np.cross(up, east)
                el = math.asin(float(sun @ up))
                az = math.degrees(math.atan2(float(sun @ east), float(sun @ north))) % 360.0
                h = float(np.interp(az, [b.azimuth_deg for b in hz.bins], [b.elevation_rad for b in hz.bins], period=360.0))
                margin_deg = math.degrees(el + sd - h)
                ours = bool(lit_mask(dem, np.array([x]), np.array([y]), sun, sd, OBSERVER_M)[0])
                ok = abs(margin_deg) <= GATE_MARGIN_DEG or ours == (margin_deg > 0)
                print(f"gate {label:16s} production margin {margin_deg:+.3f} deg, ray march {'lit' if ours else 'dark'} "
                      f"-> {'OK' if ok else 'MISMATCH'}", flush=True)
                if not ok:
                    print("Gate failed: the ray march disagrees with the production horizon. Nothing scored.")
                    return 2
            gate_done = True

        with rasterio.open(names[name]) as ds:
            check_crs(ds.crs.to_wkt())
            t = ds.transform
            half = int(DISC_KM * 1000 / t.a)
            cr, cc = int(round(-t.f / t.e)), int(round(-t.c / t.a))
            full = ds.read(1)
            photo = full[cr - half:cr + half, cc - half:cc + half]
            inside = footprint(full > 0)[cr - half:cr + half, cc - half:cc + half]
        cols = np.arange(cc - half, cc + half)
        rows = np.arange(cr - half, cr + half)
        xs, ys = np.meshgrid(t.c + (cols + 0.5) * t.a, t.f + (rows + 0.5) * t.e)
        disc = np.hypot(xs, ys) <= DISC_KM * 1000
        coverage = float((inside & disc).sum() / disc.sum())
        if coverage < MIN_COVERAGE:
            print(f"{name}: strip covers {coverage:.0%} of the disc (< {MIN_COVERAGE:.0%}), not scored")
            results.append({"frame": name, "utc": when.isoformat(), "coverage": coverage, "scored": False})
            continue
        print(f"{name}: rendering {xs.size} pixels ...", flush=True)
        model = lit_mask(dem, xs, ys, sun, sd, OBSERVER_M)
        threshold = otsu(photo[inside & disc])
        photo_lit = photo >= threshold
        scored = inside & disc & ~edge_band(model, int(EDGE_BAND_M / t.a))
        s = score(model, photo_lit, scored)
        passed = s["agreement"] >= PASS_AGREEMENT and s["shadow_iou"] >= PASS_IOU
        # Diagnostics added after the first run (not part of the verdict): how much better than trivial
        # models, and how good including the excluded edge band.
        everything = inside & disc
        base_dark = float((~photo_lit[scored]).mean())
        lit_union = (model | photo_lit)[scored].sum()
        diag = {
            "photo_shadow_fraction": base_dark,
            "all_dark_baseline_agreement": base_dark,
            "all_lit_baseline_agreement": 1.0 - base_dark,
            "lit_iou": float((model & photo_lit)[scored].sum() / lit_union) if lit_union else 1.0,
            "with_edge_band": score(model, photo_lit, everything),
            "edge_band_share_of_disc": float((everything & ~scored).sum() / max(everything.sum(), 1)),
        }
        sub_lon = sky["series"]["sun"]["sub_lon_east_deg"][0]
        print(f"{name}: Sun toward {sub_lon:.1f} E, {math.degrees(math.asin(-sun[2])):+.2f} deg above the horizontal "
              f"at the pole; Otsu {threshold}; agreement {s['agreement']:.1%}, shadow IoU {s['shadow_iou']:.2f} -> "
              f"{'PASS' if passed else 'FAIL'}", flush=True)
        print(f"    diagnostics: photo is {base_dark:.0%} shadow (all-dark guess would agree {base_dark:.1%}); "
              f"lit-area IoU {diag['lit_iou']:.2f}; including the edge band ({diag['edge_band_share_of_disc']:.0%} of the "
              f"imaged disc): agreement {diag['with_edge_band']['agreement']:.1%}, shadow IoU "
              f"{diag['with_edge_band']['shadow_iou']:.2f}", flush=True)
        results.append({"frame": name, "utc": when.isoformat(), "coverage": coverage, "scored": True,
                        "otsu_threshold": threshold, "passed": passed, **s, "diagnostics_post_hoc": diag})

        g = photo.astype(float)
        panel_model = np.where(model, 200.0, 15.0)
        diff = np.zeros(photo.shape + (3,))
        diff[model & photo_lit] = (200, 200, 200)
        diff[model & ~photo_lit] = (220, 60, 60)      # red: we say lit, LRO dark
        diff[~model & photo_lit] = (60, 120, 230)     # blue: we say dark, LRO lit
        for arr in (g, panel_model):
            arr[~inside] = 0
        diff[~inside] = (60, 0, 60)
        sep = np.full((photo.shape[0], 6, 3), 255.0)
        img = np.concatenate([np.stack([g] * 3, -1), sep, np.stack([panel_model] * 3, -1), sep, diff], 1)
        write_png(out_dir / f"{name}_compare.png", img)

    scored = [r for r in results if r.get("scored")]
    overall = (sum(r["passed"] for r in scored) >= math.ceil(2 * len(scored) / 3)) if scored else None
    print(f"\n{sum(r['passed'] for r in scored)}/{len(scored)} scored frames pass -> "
          f"{'PASS' if overall else 'FAIL' if overall is not None else 'NOTHING SCORED'}")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (out_dir / f"shadow_match_{stamp}.json").write_text(json.dumps({
        "created_utc": stamp, "frames": results, "overall_pass": overall,
        "rules": {"disc_km": DISC_KM, "observer_m": OBSERVER_M, "edge_band_m": EDGE_BAND_M,
                  "min_coverage": MIN_COVERAGE, "pass_agreement": PASS_AGREEMENT, "pass_iou": PASS_IOU},
    }, indent=2), encoding="utf-8")
    print(f"pictures and report in {out_dir.relative_to(ROOT)} (left: LRO photo, middle: our shadows, "
          "right: grey agree, red we-say-lit, blue we-say-dark, purple not imaged)")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())
