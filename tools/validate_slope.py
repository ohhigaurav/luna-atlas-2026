#!/usr/bin/env python3
"""Gate S: our computed slope vs NASA PGDA's published slope maps at Sites 001 and 004 (D-23).

The pass rule is ``validation/slope_tolerances.json``, written before this tool first ran. The
tool never edits it. Every run writes dated evidence (.md, .json, .log) to validation/evidence/,
PASS or FAIL, and a FAIL stays there.

    # 1. once: download the published slope + slope-error layers and record their hashes
    .venv/bin/python tools/validate_slope.py --fetch
    # 2. compare (needs the 5 m surface DEMs already in data/dems/assets/)
    .venv/bin/python tools/validate_slope.py

Exit code: 0 PASS, 1 FAIL, 2 inputs missing or unverified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

TOLERANCES = ROOT / "validation" / "slope_tolerances.json"
EVIDENCE = ROOT / "validation" / "evidence"
SITES = {"pgda78-site01-surface": "reference-lola-site-001", "pgda78-site04-surface": "reference-lola-site-004"}
MAX_LAYER_BYTES = 200_000_000


# ------------------------------------------------------------------ pure comparison (unit-tested)


def compare(ours: Any, published: Any, domain: Any, crit: dict[str, Any]) -> dict[str, Any]:
    """S2-S5 over ``domain`` pixels. ``ours``/``published`` in degrees, NaN = unknown."""
    import numpy as np

    o, p = np.asarray(ours, dtype=float)[domain], np.asarray(published, dtype=float)[domain]
    both = np.isfinite(o) & np.isfinite(p)
    n_dom, n = int(o.size), int(both.sum())
    out: dict[str, Any] = {"domain_pixels": n_dom, "compared_pixels": n,
                           "coverage_share": n / n_dom if n_dom else 0.0}
    if n == 0:
        out.update(checks={"S2": False, "S3": False, "S4": False, "S5": False})
        return out
    d = o[both] - p[both]
    ad = np.abs(d)
    lim = float(crit["S5_limit_deg"])
    disagree = float(np.mean((o[both] <= lim) != (p[both] <= lim)))
    out.update({
        "difference_deg": {"median": float(np.median(d)), "mean": float(np.mean(d)),
                           "rms": float(np.sqrt(np.mean(d * d))), "p95_abs": float(np.quantile(ad, 0.95)),
                           "p99_abs": float(np.quantile(ad, 0.99)), "max_abs": float(ad.max())},
        "ours_deg": {"median": float(np.median(o[both])), "p90": float(np.quantile(o[both], 0.9))},
        "published_deg": {"median": float(np.median(p[both])), "p90": float(np.quantile(p[both], 0.9))},
        "limit_disagreement_share": disagree,
    })
    out["checks"] = {
        "S2": out["coverage_share"] >= float(crit["S2_coverage_min_share"]),
        "S3": abs(out["difference_deg"]["median"]) <= float(crit["S3_abs_median_difference_max_deg"]),
        "S4": out["difference_deg"]["p95_abs"] <= float(crit["S4_p95_abs_difference_max_deg"]),
        "S5": disagree <= float(crit["S5_limit_disagreement_max_share"]),
    }
    return out


def verdict(per_site: dict[str, dict[str, Any]]) -> str:
    ok = per_site and all(r.get("S1_same_grid") and all(r["primary"]["checks"].values()) for r in per_site.values())
    return "PASS" if ok else "FAIL"


# ------------------------------------------------------------------ inputs


def _git() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return ""
    return {"commit": run("rev-parse", "HEAD") or None, "dirty": bool(run("status", "--porcelain"))}


def fetch(force: bool) -> int:
    from lunar_core.provenance import sha256_file
    from lunar_core.slope import SLOPE_LAYERS

    from tools.prepare_public_inputs import PGDA_HOSTS, download_atomic

    doc = json.loads(SLOPE_LAYERS.read_text(encoding="utf-8"))
    for layer in doc["layers"]:
        dest = ROOT / layer["relative_path"]
        if dest.exists() and not force:
            if layer.get("sha256") and sha256_file(dest) == layer["sha256"]:
                print(f"{layer['layer_id']}: present, hash matches")
                continue
            print(f"{layer['layer_id']}: {dest.name} exists but is not recorded; re-run with --force to re-download")
            return 2
        print(f"{layer['layer_id']}: downloading {layer['source_url']}", flush=True)
        try:
            got = download_atomic(layer["source_url"], dest, allowed_hosts=PGDA_HOSTS, max_bytes=MAX_LAYER_BYTES,
                                  force=force)
        except Exception as exc:  # noqa: BLE001 - report and keep the manifest unchanged for this layer
            print(f"  failed: {exc}")
            continue
        layer.update(sha256=got["sha256"], size_bytes=got["size_bytes"], retrieved_utc=got["retrieved_utc"])
        print(f"  {got['size_bytes']:,} bytes, sha256 {got['sha256']}")
    SLOPE_LAYERS.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def _read_full(path: Path, units: str) -> tuple[Any, dict[str, Any]]:
    """Whole band 1 (NaN = unknown) plus the grid metadata, captured while the file is open."""
    import rasterio
    from lunar_core.terrain import _physical_grid_m

    with rasterio.open(path) as ds:
        raw = ds.read(1, masked=True)
        values = _physical_grid_m(ds, raw, "m" if units == "deg" else units)
        return values, {"crs": ds.crs, "transform": ds.transform, "width": ds.width, "height": ds.height}


# ------------------------------------------------------------------ the run


def run(output_dir: Path) -> int:
    import numpy as np
    from lunar_core import analysis_service, slope
    from lunar_core.terrain import _crs_equivalent, load_dem_manifest

    tol_text = TOLERANCES.read_text(encoding="utf-8")
    tol = json.loads(tol_text)
    crit = tol["criteria"]
    manifest = load_dem_manifest(analysis_service.DEM_MANIFEST)
    layers = slope.load_layers()
    sites = analysis_service._load_sites()
    R = manifest.body_radius_m
    started = datetime.now(UTC)
    log: list[str] = [f"{started.isoformat(timespec='seconds')} Gate S run; tolerances status={tol['status']}"]
    per_site: dict[str, dict[str, Any]] = {}
    missing: list[str] = []

    for asset in manifest.assets:
        if asset.asset_id not in SITES:
            continue
        site = sites[SITES[asset.asset_id]]
        dem_path = ROOT / asset.relative_path
        ref = slope.companion(asset.asset_id, "slope_deg", ROOT, layers)
        if not dem_path.is_file() or not slope._verified(dem_path, asset.sha256):
            missing.append(f"{asset.asset_id}: surface DEM missing or hash mismatch")
            continue
        if ref is None:
            missing.append(f"{asset.asset_id}: published slope layer not staged (run --fetch)")
            continue
        z, dem_ds = _read_full(dem_path, asset.elevation_units)
        pub, pub_ds = _read_full(ref[0], "deg")
        same = (_crs_equivalent(dem_ds["crs"], pub_ds["crs"])
                and tuple(dem_ds["transform"])[:6] == tuple(pub_ds["transform"])[:6]
                and (dem_ds["width"], dem_ds["height"]) == (pub_ds["width"], pub_ds["height"]))
        rec: dict[str, Any] = {"site_id": site["site_id"], "dem_sha256": asset.sha256, "published_layer": ref[1],
                               "S1_same_grid": bool(same)}
        log.append(f"{asset.asset_id}: S1 same grid = {same}")
        if same:
            t = dem_ds["transform"]
            h, w = z.shape
            xs = t.c + (np.arange(w) + 0.5) * t.a
            ys = t.f + (np.arange(h) + 0.5) * t.e
            k_full = slope.stereo_scale_factor(xs[None, :], ys[:, None], R)
            ours = slope.horn_slope_deg(z, t.a, -t.e, k_full)
            diag = slope.central_slope_deg(z, t.a, -t.e, k_full)
            interior = np.zeros((h, w), dtype=bool)
            interior[1:-1, 1:-1] = True
            # Domain: pixel centres within 1500 m (geodesic) of the site, searched in a 1600 m map box.
            from lunar_core.terrain import south_polar_stereo_m
            x0, y0 = south_polar_stereo_m(float(site["latitude_deg"]), float(site["longitude_deg"]), R)
            c0, c1 = max(1, int((x0 - 1600 - t.c) / t.a)), min(w - 1, int((x0 + 1600 - t.c) / t.a) + 1)
            r0, r1 = max(1, int((t.f - (y0 + 1600)) / -t.e)), min(h - 1, int((t.f - (y0 - 1600)) / -t.e) + 1)
            X, Y = np.meshgrid(xs[c0:c1], ys[r0:r1])
            lat, lon = slope.stereo_to_latlon(X, Y, R)
            e, n = slope.local_east_north(float(site["latitude_deg"]), float(site["longitude_deg"]), lat, lon, R)
            domain = np.zeros((h, w), dtype=bool)
            domain[r0:r1, c0:c1] = np.hypot(e, n) <= 1500.0
            rec["primary"] = compare(ours, pub, domain, crit)
            rec["diagnostic_central_difference"] = compare(diag, pub, domain, crit)
            rec["diagnostic_whole_tile"] = compare(ours, pub, interior, crit)
            log.append(f"{asset.asset_id}: primary {json.dumps(rec['primary'], sort_keys=True)}")
        else:
            rec["primary"] = {"checks": {"S2": False, "S3": False, "S4": False, "S5": False},
                              "note": "grids differ; no resampling by rule"}
        per_site[asset.asset_id] = rec

    if missing:
        for m in missing:
            print("missing:", m)
        print("No evidence written: inputs are incomplete (exit 2).")
        return 2

    result = verdict(per_site)
    stamp = started.strftime("%Y-%m-%d")
    base = output_dir / f"slope_check_{stamp}"
    evidence = {
        "gate": "S", "verdict": result, "run_utc": started.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "tolerances": {"path": str(TOLERANCES.relative_to(ROOT)), "sha256": hashlib.sha256(tol_text.encode()).hexdigest(),
                       "status_at_run": tol["status"], "predeclared_utc": tol["predeclared_utc"], "criteria": crit},
        "method": {"algorithm": slope.SLOPE_ALGORITHM, "production_source_at_run": slope.SLOPE_SOURCE},
        "git": _git(), "sites": per_site,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    base.with_suffix(".json").write_text(json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    base.with_suffix(".log").write_text("\n".join(log) + "\n", encoding="utf-8")
    base.with_suffix(".md").write_text(report(evidence), encoding="utf-8")
    print(report(evidence))
    print(f"evidence: {base}.md / .json / .log")
    return 0 if result == "PASS" else 1


def _checks(checks: dict[str, bool]) -> str:
    return " ".join(f"{k}:" + ("ok" if v else "FAIL") for k, v in checks.items())


def report(ev: dict[str, Any]) -> str:
    c = ev["tolerances"]["criteria"]
    lines = [f"# Gate S: computed slope vs PGDA published slope — {ev['verdict']}", "",
             f"Run {ev['run_utc']}, commit {ev['git']['commit']}{' (dirty)' if ev['git']['dirty'] else ''}. "
             f"Pass rule `{ev['tolerances']['path']}` (sha256 {ev['tolerances']['sha256'][:16]}…, predeclared "
             f"{ev['tolerances']['predeclared_utc']}, status at run: {ev['tolerances']['status_at_run']}).", "",
             f"Rule: same grid; coverage ≥ {c['S2_coverage_min_share']:.0%}; |median diff| ≤ {c['S3_abs_median_difference_max_deg']}°; "
             f"p95 |diff| ≤ {c['S4_p95_abs_difference_max_deg']}°; ≤ {c['S5_limit_disagreement_max_share']:.0%} disagreement "
             f"at {c['S5_limit_deg']}°. Domain: pixels within 1500 m of the site point.", "",
             "| Site | S1 grid | coverage | median diff | p95 abs diff | disagree at limit | checks |",
             "|---|---|---|---|---|---|---|"]
    for r in ev["sites"].values():
        p = r["primary"]
        d = p.get("difference_deg", {})
        fmt = lambda v, s="": "—" if v is None or (isinstance(v, float) and not math.isfinite(v)) else f"{v:.3f}{s}"  # noqa: E731
        lines.append(f"| {r['site_id']} | {r['S1_same_grid']} | {fmt(p.get('coverage_share'))} | {fmt(d.get('median'), '°')} | "
                     f"{fmt(d.get('p95_abs'), '°')} | {fmt(p.get('limit_disagreement_share'))} | "
                     f"{_checks(p['checks'])} |")
    lines += ["", "Diagnostics (not part of the verdict): central differences and whole-tile statistics are in the .json.",
              "", "Meaning: " + ("the computed slope may be shown with 'checked against the NASA PGDA slope map at Sites 001 and 004'."
                                 if ev["verdict"] == "PASS" else
                                 "FAIL is kept. Per the pre-registered consequence, set lunar_core.slope.SLOPE_SOURCE = "
                                 "'published' and label computed slope elsewhere 'not checked'."), ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fetch", action="store_true", help="download the PGDA slope and slope-error layers")
    parser.add_argument("--force", action="store_true", help="with --fetch: re-download existing files")
    parser.add_argument("--out", type=Path, default=EVIDENCE)
    args = parser.parse_args()
    return fetch(args.force) if args.fetch else run(args.out)


if __name__ == "__main__":
    raise SystemExit(main())
