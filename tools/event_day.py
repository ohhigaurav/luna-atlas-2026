#!/usr/bin/env python3
"""Event day (13 Nov): official site list -> catalogue -> every answer pre-computed -> report.

    # 1. read the dry run (writes nothing); fix what it refuses (docs/official_site_import.md)
    .venv/bin/python tools/event_day.py <file> --source-url <resources page URL> [import options]
    # 2. import and pre-compute
    .venv/bin/python tools/event_day.py <file> --source-url <URL> [import options] --write
    # (already imported: skip step 1 and only pre-compute and report)
    .venv/bin/python tools/event_day.py --skip-import

Import options are passed to tools/import_official_sites.py unchanged:
--longitude-direction, --latitude-type, --column ROLE=HEADER (repeatable), --sheet.

After the import, every official site is asked the app's default landing question: from today
00:00 UTC, 90 days, 10-day mission, Sun at most 20 deg, Earth in view at touchdown (the same as
lunar_core.warm). The answers land in the cache the app reads, so the pins are ready. Polar
official sites (south of 60 S) are also compared side by side at today 00:00 UTC.

Sanity checks in the report:
  * the nearest reference point to each official site, and the distance to it. An official site
    and a stand-in for the same mission should be metres to hundreds of metres apart; kilometres
    or more means a sign or convention problem to resolve before trusting anything;
  * which terrain each answer used: 5 m site tile, 240 m regional map, or flat horizon.

Report: data/derived/event_day_report_<stamp>.md (and .json). Next steps are printed at the end.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

R_MOON_KM = 1737.4
POLAR_LIMIT_DEG = -60.0
SANITY_KM = 5.0


def surface_km(lat1: float, lon1: float, lat2: float, lon2: float, radius_km: float = R_MOON_KM) -> float:
    """Great-circle distance on the reference sphere (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius_km * math.asin(min(1.0, math.sqrt(a)))


def nearest_reference(lat: float, lon: float, refs: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    best, dist = None, math.inf
    for r in refs:
        d = surface_km(lat, lon, float(r["latitude_deg"]), float(r["longitude_deg"]))
        if d < dist:
            best, dist = r, d
    return best, dist


def import_command(args: argparse.Namespace) -> list[str]:
    cmd = [sys.executable, str(ROOT / "tools" / "import_official_sites.py"), str(args.source), "--source-url", args.source_url]
    if args.longitude_direction:
        cmd += ["--longitude-direction", args.longitude_direction]
    if args.latitude_type:
        cmd += ["--latitude-type", args.latitude_type]
    for c in args.column or []:
        cmd += ["--column", c]
    if args.sheet:
        cmd += ["--sheet", args.sheet]
    if not args.write:
        cmd.append("--dry-run")
    return cmd


def _terrain_label(landing: dict[str, Any]) -> str:
    t = landing.get("terrain") or {}
    finest = t.get("finest_resolution_m")
    return f"{finest:g} m" if finest else str(landing.get("horizon_mode") or "–")


def _fmt_h(hours: float | None, lower: bool = False) -> str:
    if hours is None:
        return "–"
    d, h = divmod(int(round(hours)), 24)
    return ("≥ " if lower else "") + (f"{d} d {h} h" if d else f"{hours:.1f} h")


def site_row(site: dict[str, Any], landing: dict[str, Any] | None, error: str | None,
             refs: list[dict[str, Any]]) -> dict[str, Any]:
    lat, lon = float(site["latitude_deg"]), float(site["longitude_deg"])
    ref, dist = nearest_reference(lat, lon, refs)
    row: dict[str, Any] = {
        "site_id": site["site_id"], "name": site["name"], "latitude_deg": lat, "longitude_deg": lon,
        "polar": lat <= POLAR_LIMIT_DEG,
        "nearest_reference": None if ref is None else {"site_id": ref["site_id"], "name": ref["name"], "km": round(dist, 3)},
        "error": error,
    }
    if landing is not None:
        opp = landing["opportunities"][0] if landing["opportunities"] else None
        row.update({
            "horizon_mode": landing.get("horizon_mode"),
            "terrain_label": _terrain_label(landing),
            "opportunity_count": landing["opportunity_count"],
            "next_window": None if opp is None else {
                "from_utc": opp["touchdown_from_utc"], "until_utc": opp["touchdown_until_utc"],
                "best_utc": opp["best_touchdown_utc"], "sun_deg": opp["sun_elevation_at_best_deg"],
                "daylight_h": opp["daylight_after_best_h"], "daylight_lower_bound": opp["daylight_is_lower_bound"],
                "earth_pct": opp["earth_in_view_during_mission_pct"],
            },
            "closest_miss": landing.get("closest_miss"),
            "summary": landing.get("summary", [None])[0],
        })
    return row


def report_markdown(rows: list[dict[str, Any]], compare: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    lines = [f"# Event-day report: {meta['created_utc']}", "",
             f"Official catalogue: {meta['official_count']} sites with coordinates "
             f"({meta['unplaced']} without), source {meta['source_url']}.",
             f"Question: from {meta['start_utc']}, 90 days, 10-day mission, Sun ≤ 20°, Earth in view at touchdown.", "",
             "| site | lat | lon (E) | terrain | next window (touchdown) | Sun at best | daylight after | Earth in mission | "
             "nearest reference (km) |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        nw = r.get("next_window")
        ref = r["nearest_reference"]
        flag = " ⚠" if ref and ref["km"] > SANITY_KM else ""
        window = ("**" + nw["from_utc"][:16] + " → " + nw["until_utc"][:16] + "**") if nw else (
            "error: " + r["error"] if r.get("error") else "none in 90 d")
        lines.append(
            f"| {r['name']} | {r['latitude_deg']:.4f} | {r['longitude_deg']:.4f} | {r.get('terrain_label') or r.get('horizon_mode') or '–'} | {window} | "
            + (f"{nw['sun_deg']:.2f}°" if nw else "–") + " | "
            + (_fmt_h(nw["daylight_h"], nw["daylight_lower_bound"]) if nw else "–") + " | "
            + (f"{nw['earth_pct']:.0f}%" if nw else "–") + " | "
            + (f"{ref['name']} ({ref['km']:.2f}){flag}" if ref else "–") + " |")
    if any(r["nearest_reference"] and r["nearest_reference"]["km"] > SANITY_KM for r in rows):
        lines += ["", f"⚠ = an official site more than {SANITY_KM:g} km from every reference point. Fine if it is "
                  "a new place; if it should match a known mission or landmark, check the longitude convention first "
                  "(a flipped sign moves a site by 2 x longitude; Malapert's NASA page may carry exactly that slip)."]
    for block in compare:
        lines += ["", f"## Polar sites side by side at {block['at_utc'][:16]} UTC (30 days)", "",
                  "| site | terrain | Sun now | next Sun event | Earth now | next Earth event | sunlit | Earth | both |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for row in block["rows"]:
            t = row["terrain"]["finest_resolution_m"]
            sn, en, n, p = row["sun_next"], row["earth_next"], row["now"], row["period"]
            lines.append(
                f"| {row['site']['name']} | {f'{t:g} m' if t else row['horizon_mode']} | "
                f"{'up' if n['sun']['up'] else 'down'} {n['sun']['elevation_deg']:+.2f}° | {sn['event']} in {_fmt_h(sn['in_h'], sn['lower_bound'])} | "
                f"{'up' if n['earth']['up'] else 'down'} | {en['event']} in {_fmt_h(en['in_h'], en['lower_bound'])} | "
                f"{p['sunlit_percent']:.0f}% | {p['earth_percent']:.0f}% | {p['both_percent']:.0f}% |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", nargs="?", type=Path)
    parser.add_argument("--source-url")
    parser.add_argument("--longitude-direction")
    parser.add_argument("--latitude-type")
    parser.add_argument("--column", action="append")
    parser.add_argument("--sheet")
    parser.add_argument("--write", action="store_true", help="import for real (default: dry run only)")
    parser.add_argument("--skip-import", action="store_true", help="use the catalogue already imported")
    parser.add_argument("--start", default=datetime.now(UTC).strftime("%Y-%m-%dT00:00:00Z"))
    args = parser.parse_args()

    if not args.skip_import:
        if args.source is None or not args.source_url:
            parser.error("give the official file and --source-url, or --skip-import")
        cmd = import_command(args)
        print("$ " + " ".join(cmd), flush=True)
        code = subprocess.call(cmd)
        if code != 0:
            print(f"\nimport stopped (exit {code}): fix what it says (docs/official_site_import.md) and run again.")
            return code
        if not args.write:
            print("\nDry run only. Read every row above; when all are right, run the same command with --write.")
            return 0

    from lunar_core.api_models import CompareRequest, LandingRequest
    from lunar_core.catalogue import load_default_catalogue
    from lunar_core.compare import run_compare
    from lunar_core.landing import run_landing
    from lunar_core.references import load_reference_catalogue
    from lunar_core.warm import MAX_SUN_DEG, MISSION_DAYS, SEARCH_DAYS

    catalogue = load_default_catalogue()
    if catalogue.catalogue_state != "loaded":
        print("The official catalogue is still empty (awaiting_official_source). Import first.")
        return 1
    refs = [s.model_dump(mode="json") for s in load_reference_catalogue().sites]
    placed = [s.model_dump(mode="json") for s in catalogue.sites if s.latitude_deg is not None and s.longitude_deg is not None]
    print(f"\n{len(placed)} official sites with coordinates; asking each the app's default landing question ...", flush=True)
    rows = []
    for i, site in enumerate(sorted(placed, key=lambda s: float(s["latitude_deg"]) <= POLAR_LIMIT_DEG), 1):
        landing, error = None, None
        try:
            landing = run_landing(LandingRequest(site_id=site["site_id"], search_start_utc=args.start, search_days=SEARCH_DAYS,
                                                 mission_days=MISSION_DAYS, max_sun_elevation_deg=MAX_SUN_DEG))
        except Exception as exc:  # report every site; one failure must not hide the rest
            error = f"{type(exc).__name__}: {exc}"
        row = site_row(site, landing, error, refs)
        rows.append(row)
        nw = row.get("next_window")
        ref = row["nearest_reference"]
        warn = f"  ⚠ {ref['km']:.1f} km from nearest reference ({ref['name']})" if ref and ref["km"] > SANITY_KM else ""
        print(f"  {i}/{len(placed)} {site['name']}: " + (error or (f"next {nw['from_utc'][:16]} → {nw['until_utc'][:16]} "
              f"({row.get('terrain_label')})" if nw else f"no window in 90 d ({row.get('terrain_label')})")) + warn, flush=True)

    polar = [r for r in rows if r["polar"] and not r.get("error")]
    compare_blocks = []
    for k in range(0, len(polar), 6):
        chunk = polar[k:k + 6]
        if len(chunk) >= 1:
            compare_blocks.append(run_compare(CompareRequest(places=[{"site_id": r["site_id"]} for r in chunk],
                                                             at_utc=args.start, days=30)))
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    meta = {"created_utc": stamp, "official_count": len(placed), "unplaced": len(catalogue.sites) - len(placed),
            "source_url": catalogue.source_url, "start_utc": args.start}
    out = ROOT / "data" / "derived" / f"event_day_report_{stamp}"
    out.parent.mkdir(parents=True, exist_ok=True)
    (out.with_suffix(".md")).write_text(report_markdown(rows, compare_blocks, meta), encoding="utf-8")
    (out.with_suffix(".json")).write_text(json.dumps({"meta": meta, "sites": rows, "compare": compare_blocks}, indent=2,
                                                     default=str), encoding="utf-8")
    print(f"\nreport: {out.with_suffix('.md').relative_to(ROOT)}")
    print("Next: restart the server (pins warm from the cache), then\n"
          "  .venv/bin/python tools/bake_static.py   # judge bundle with the official sites\n"
          "  git add data/catalogue && git commit -m 'Import official challenge sites' && git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
