#!/usr/bin/env python3
"""Bake the API answers the app asks for, so the static judge site works with no server.

Judging continues for weeks after 15 Nov and no laptop stays on, so the judged site is static.
Without this, static mode could not show compare, landing windows, the landing ellipse or the 3D
ground view: the challenge's core asks. This calls the real endpoints' functions and saves each
response unmodified, under the key the frontend builds from its own request
(``lunar_core.static_answers``; frontend mirror ``src/data/staticAnswers.ts``).

Baked, for every site in the site index (official sites first, once imported):
  * landing windows: the app's default question from the bundle start (90 d search, 10-day
    mission, Sun <= 20 deg, R5 auto);
  * check: start + 60 d and start+60 d + 30 d (the landing ring's two calls); plus start + 30 d
    at panel heights 0, 1, 2, 5, 10 m for polar sites (the 3D ground view's mast menu); the saved
    runs behind those 30-day checks are copied, for GET /api/runs/{id};
  * compare, one place at a time (the frontend merges places): at start + 0, 7, 14 and 21 days,
    30 days each;
  * landing ellipse: Sites 001 and 004 (polar sites with 5 m tiles), round, semi-axis 100, 250,
    500 and 1000 m, 14 days from start.

Times not baked show "precomputed for <date>" in static mode (the clock snaps to ``baked_times``).

Resumable: answers already in the index with their file present are kept.

    .venv/bin/python tools/bake_answers.py [--start 2027-01-01T00:00:00Z] [--out frontend/app/public/data]
                                           [--only landing,check,compare,ellipse]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

POLAR_LIMIT_DEG = -60.0
COMPARE_OFFSETS_D = (0, 7, 14, 21)
MAST_HEIGHTS_M = (0, 1, 2, 5, 10)
ELLIPSE_SITES = ("reference-lola-site-001", "reference-lola-site-004")
ELLIPSE_SIZES_M = (100, 250, 500, 1000)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan(sites: list[dict[str, Any]], start: datetime) -> list[tuple[str, dict[str, Any]]]:
    """(endpoint, request body) pairs, exactly as the frontend sends them."""
    s0, s60 = iso(start), iso(start + timedelta(days=60))
    out: list[tuple[str, dict[str, Any]]] = []
    for site in sites:
        sid, polar = site["site_id"], float(site["latitude_deg"]) <= POLAR_LIMIT_DEG
        out.append(("landing-windows", {"site_id": sid, "search_start_utc": s0, "search_days": 90, "mission_days": 10,
                                        "max_sun_elevation_deg": 20}))
        out.append(("check", {"site_id": sid, "start_utc": s0, "days": 60, "panel_height_m": 2}))
        out.append(("check", {"site_id": sid, "start_utc": s60, "days": 30, "panel_height_m": 2}))
        for h in (MAST_HEIGHTS_M if polar else (2,)):
            out.append(("check", {"site_id": sid, "start_utc": s0, "days": 30, "panel_height_m": h}))
        for d in COMPARE_OFFSETS_D:
            out.append(("compare", {"site_id": sid, "at_utc": iso(start + timedelta(days=d)), "days": 30,
                                    "panel_height_m": 2}))
    for sid in ELLIPSE_SITES:
        if any(s["site_id"] == sid for s in sites):
            for a in ELLIPSE_SIZES_M:
                out.append(("landing-ellipse", {"site_id": sid, "start_utc": s0, "days": 14, "semi_major_m": a,
                                                "semi_minor_m": a, "orientation_deg": 0, "panel_height_m": 2}))
    return out


def answer(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    from lunar_core.api_models import CheckRequest, CompareRequest, EllipseRequest, LandingRequest
    if endpoint == "landing-windows":
        from lunar_core.landing import run_landing
        return run_landing(LandingRequest(**body))
    if endpoint == "check":
        from lunar_core.check import run_check
        return run_check(CheckRequest(**body))
    if endpoint == "compare":
        from lunar_core.compare import run_compare
        place = {k: body[k] for k in ("site_id", "latitude_deg", "longitude_deg") if k in body}
        return run_compare(CompareRequest(places=[place], at_utc=body["at_utc"], days=body["days"],
                                          panel_height_m=body["panel_height_m"]))
    if endpoint == "landing-ellipse":
        from lunar_core.landing_ellipse import run_landing_ellipse
        return run_landing_ellipse(EllipseRequest(**body))
    raise ValueError(endpoint)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", default="2027-01-01T00:00:00Z")
    parser.add_argument("--out", type=Path, default=ROOT / "frontend/app/public/data")
    parser.add_argument("--only", default="landing,check,compare,ellipse")
    args = parser.parse_args()

    from lunar_core.analysis_service import RUNS_DIR
    from lunar_core.api import site_index
    from lunar_core.cache_keys import write_atomic
    from lunar_core.static_answers import KEY_SPEC, make_key

    start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
    wanted = {"landing": "landing-windows", "check": "check", "compare": "compare", "ellipse": "landing-ellipse"}
    endpoints = {wanted[x.strip()] for x in args.only.split(",") if x.strip()}
    out = args.out
    index_path = out / "answers" / "index.json"
    previous = json.loads(index_path.read_text(encoding="utf-8")) if index_path.is_file() else {}
    answers: dict[str, str] = dict(previous.get("answers", {}))
    runs: dict[str, str] = dict(previous.get("runs", {}))
    errors: dict[str, str] = {}

    sites = site_index()["sites"]
    todo = [(e, b) for e, b in plan(sites, start) if e in endpoints]
    print(f"{len(todo)} answers planned for {len(sites)} sites from {iso(start)}", flush=True)
    started = time.monotonic()
    for i, (endpoint, body) in enumerate(todo, 1):
        key = make_key(endpoint, body)
        if key in answers and (out / answers[key]).is_file():
            continue
        t0 = time.monotonic()
        try:
            result = answer(endpoint, body)
        except Exception as exc:  # recorded in the index; the app shows the reason
            errors[key] = f"{type(exc).__name__}: {exc}"
            print(f"  [{i}/{len(todo)}] {key[:110]}: FAILED {errors[key][:120]}", flush=True)
            continue
        text = json.dumps({**result, "cache_hit": False, "static_answer": True}, allow_nan=False)
        rel = f"answers/{endpoint}/{hashlib.sha256(key.encode()).hexdigest()[:20]}.json"
        write_atomic(out / rel, text)
        answers[key] = rel
        # The 3D ground view reads the saved run behind a 30-day check (GET /api/runs/{id}); only
        # those runs are copied (each is ~0.5 MB; the others are never fetched).
        surface = endpoint == "check" and body["days"] == 30 and body["start_utc"] == iso(start)
        for run_id in ([result["run_id"]] if surface else []):
            src = RUNS_DIR / f"{run_id}.json"
            if run_id not in runs and src.is_file():
                (out / "runs").mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, out / "runs" / f"{run_id}.json")
                runs[run_id] = f"runs/{run_id}.json"
        print(f"  [{i}/{len(todo)}] {key[:110]} ({time.monotonic() - t0:.1f} s)", flush=True)

    baked_times = sorted({iso(start + timedelta(days=d)) for d in COMPARE_OFFSETS_D})
    index = {
        "schema_version": "1.0", "kind": "luna_atlas_static_answers",
        "generated_utc": iso(datetime.now(UTC)), "start_utc": iso(start),
        "key_spec": KEY_SPEC, "baked_times": baked_times,
        "answers": dict(sorted(answers.items())), "runs": dict(sorted(runs.items())),
        "errors": errors,
        "note": "Unmodified API responses keyed as in lunar_core.static_answers; other requests need the live server.",
    }
    write_atomic(index_path, json.dumps(index, indent=1))
    size = sum(p.stat().st_size for p in (out / "answers").rglob("*.json")) / 1e6
    print(f"\n{len(answers)} answers, {len(runs)} runs, {len(errors)} failed; answers {size:.1f} MB; "
          f"{time.monotonic() - started:.0f} s. Index: {index_path}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
