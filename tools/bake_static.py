#!/usr/bin/env python3
"""Bake a static data bundle so the 3D app runs with no backend (the judge site).

Every file holds an unmodified API response, so the frontend reads it with the same types and
code as live mode. Nothing is computed here that the API would not compute; this only calls the
production services and writes their output.

Output (default frontend/app/public/data/, copied into dist/ by `npm run build`):

    manifest.json            index: window, provenance, one entry per site and per baked run
    reference-sites.json     = GET  /api/reference-sites
    sky.json                 = POST /api/sky-geometry for the window
    runs/<run_id>.json       = POST /api/analysis (one site per file)

Which runs:
  * sites at or south of 60 S: terrain horizon, Sun observer height 0, 1, 2, 5 and 10 m
    (the F16 mast slider), antenna height 2 m. If terrain is not available for a site the
    reason is recorded and a flat run is baked instead, labelled as such;
  * other sites: flat horizon at 2 m only (no DEM north of 60 S, decision D-22).
Runs are one site each, so one site's terrain gap cannot fail another site's run.

Resumable: a run already listed in an existing manifest with its file present is not redone.

    .venv/bin/python tools/bake_static.py [--start 2027-01-01T00:00:00Z --end 2027-01-31T00:00:00Z]
                                          [--step-min 30] [--heights 0 1 2 5 10] [--out DIR]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

SCHEMA_VERSION = "1.0"
POLAR_LIMIT_DEG = -60.0
DEFAULT_HEIGHTS = (0.0, 1.0, 2.0, 5.0, 10.0)
FLAT_HEIGHT_M = 2.0


def run_key(site_id: str, mode: str, sun_height_m: float) -> str:
    """Stable lookup key used by the frontend: '<site_id>|<mode>|<height>m'."""
    return f"{site_id}|{mode}|{sun_height_m:g}m"


def plan_runs(sites: list[dict[str, Any]], heights: tuple[float, ...]) -> list[tuple[str, str, float]]:
    """(site_id, mode, Sun observer height) for every run to bake, in a stable order."""
    plan: list[tuple[str, str, float]] = []
    for site in sorted(sites, key=lambda s: s["site_id"]):
        if site["latitude_deg"] <= POLAR_LIMIT_DEG:
            plan.extend((site["site_id"], "terrain", h) for h in heights)
        else:
            plan.append((site["site_id"], "flat", FLAT_HEIGHT_M))
    return plan


def write_json_atomic(path: Path, payload: Any) -> str:
    """Write compact JSON atomically; return its SHA-256 (recorded in the manifest)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return hashlib.sha256(data).hexdigest()


def load_previous(manifest_path: Path, settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Runs from an earlier bake with identical settings whose files still exist."""
    if not manifest_path.is_file():
        return {}
    previous = json.loads(manifest_path.read_text(encoding="utf-8"))
    if previous.get("settings") != settings:
        return {}
    return {key: entry for key, entry in previous.get("runs", {}).items()
            if (manifest_path.parent / entry["file"]).is_file()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2027-01-01T00:00:00Z")
    parser.add_argument("--end", default="2027-01-31T00:00:00Z")
    parser.add_argument("--step-min", type=int, default=30)
    parser.add_argument("--heights", type=float, nargs="+", default=list(DEFAULT_HEIGHTS))
    parser.add_argument("--out", type=Path, default=ROOT / "frontend/app/public/data")
    args = parser.parse_args()

    from lunar_core import __version__
    from lunar_core.analysis_service import (
        TerrainNotReady,
        _git_commit,
        run_analysis,
        run_sky_geometry,
    )
    from lunar_core.api import list_reference_sites
    from lunar_core.api_models import AnalysisRequest, SkyGeometryRequest

    out: Path = args.out
    settings = {"start_utc": args.start, "end_utc": args.end, "step_min": args.step_min,
                "heights_m": sorted(args.heights), "flat_height_m": FLAT_HEIGHT_M, "antenna_height_m": 2.0}
    manifest_path = out / "manifest.json"
    previous = load_previous(manifest_path, settings)

    refs = list_reference_sites()
    files = {"reference_sites": "reference-sites.json", "sky": "sky.json"}
    hashes = {"reference_sites": write_json_atomic(out / files["reference_sites"], refs)}
    print(f"sky geometry {args.start} -> {args.end} ...", flush=True)
    sky = run_sky_geometry(SkyGeometryRequest(start_utc=args.start, end_utc=args.end, step_min=args.step_min))
    hashes["sky"] = write_json_atomic(out / files["sky"], sky)

    runs: dict[str, dict[str, Any]] = {}
    notes: dict[str, str] = {}
    no_terrain: set[str] = set()
    plan = plan_runs(refs["sites"], tuple(sorted(args.heights)))
    print(f"{len(plan)} runs planned, {sum(1 for p in plan if run_key(*p) in previous)} already baked", flush=True)

    def bake(index: int, site_id: str, mode: str, height: float) -> None:
        key = run_key(site_id, mode, height)
        request = AnalysisRequest(
            site_ids=[site_id], start_utc=args.start, end_utc=args.end, coarse_step_min=args.step_min,
            horizon_mode=mode, sun_observer_height_m=height, antenna_height_m=2.0,
        )
        started = time.monotonic()
        result = run_analysis(request)
        rel = f"runs/{result['run_id']}.json"
        digest = write_json_atomic(out / rel, result)
        metrics = result["sites"][0]["metrics"]
        runs[key] = {"file": rel, "sha256": digest, "run_id": result["run_id"], "site_id": site_id,
                     "horizon_mode": result["settings"]["horizon_mode"], "sun_observer_height_m": height,
                     "sunlit_percent": metrics.get("sunlit_percent"), "dte_clear_percent": metrics.get("dte_clear_percent")}
        print(f"[{index}/{len(plan)}] {key}: sunlit {metrics.get('sunlit_percent')} %, "
              f"Earth {metrics.get('dte_clear_percent')} % ({time.monotonic() - started:.0f} s)", flush=True)

    for index, (site_id, mode, height) in enumerate(plan, 1):
        key = run_key(site_id, mode, height)
        if key in previous:
            runs[key] = previous[key]
            continue
        if site_id in no_terrain:
            continue
        try:
            bake(index, site_id, mode, height)
        except TerrainNotReady as exc:
            # Recorded, never hidden: the site gets one flat run, labelled flat in its key and payload.
            no_terrain.add(site_id)
            notes[site_id] = f"terrain unavailable, flat horizon baked instead: {exc}"
            print(f"[{index}/{len(plan)}] {key}: terrain unavailable ({exc}); baking flat at {FLAT_HEIGHT_M:g} m", flush=True)
            bake(index, site_id, "flat", FLAT_HEIGHT_M)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "luna_atlas_static_bundle",
        "generated_utc": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "software_version": __version__,
        "git_commit": _git_commit(),
        "kernel_manifest_sha256": sky["provenance"]["kernel_manifest_sha256"],
        "settings": settings,
        "files": files,
        "file_sha256": hashes,
        "run_key_format": "<site_id>|<terrain|flat>|<sun_observer_height_m>m",
        "runs": dict(sorted(runs.items())),
        "notes": notes,
        "disclaimer": ("Precomputed results for the window above. Run the project locally for other dates, "
                       "custom points or settings. Reference sites are not official challenge coordinates."),
    }
    write_json_atomic(manifest_path, manifest)
    size_mb = sum(p.stat().st_size for p in out.rglob("*.json")) / 1e6
    print(f"wrote {manifest_path.relative_to(ROOT) if manifest_path.is_relative_to(ROOT) else manifest_path}: "
          f"{len(runs)} runs, {size_mb:.1f} MB")
    if manifest["git_commit"] is None:
        print("note: git_commit is null because the working tree has uncommitted changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
