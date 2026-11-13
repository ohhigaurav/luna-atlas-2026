#!/usr/bin/env python3
"""Gate P: check the sunlight-power layer on real data against rules fixed before the run.

Reads validation/power_tolerances.json (must be approved before the run), asks the API the
predeclared /api/compare questions, and writes validation/evidence/power_check_<date>.md and .json.
Standard library only:

    python3 tools/power_check.py                                   # live server
    python3 tools/power_check.py --base http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "validation" / "power_tolerances.json"
EVIDENCE = ROOT / "validation" / "evidence"
LIVE = "https://13-54-224-119.sslip.io"


def post(base: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method="GET" if body is None else "POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path}: HTTP {e.code} {e.read()[:300]!r}") from None


def check_row(row: dict[str, Any], c: dict[str, Any], start_utc: str) -> list[tuple[str, bool, str]]:
    p, disc = row["period"].get("power"), row["period"].get("sun_disc_percent")
    if p is None or disc is None:
        return [("P0_power_present", False, "no power or disc value in the response")]
    out = [("P1", p["peak_vertical_w_m2"] <= c["P1_peak_vertical_max_w_m2"], f"peak {p['peak_vertical_w_m2']:.1f}")]
    fr = p.get("first_sunrise")
    if fr and fr.get("full_disc_reached"):
        out.append(("P2", p["peak_vertical_w_m2"] >= c["P2_peak_vertical_min_w_m2_when_full_disc_reached"],
                    f"peak {p['peak_vertical_w_m2']:.1f} with a full disc"))
    if disc > c["P3_applies_when_sun_disc_percent_above"]:
        ratio = p["mean_vertical_w_m2"] / (13.61 * disc)
        lo, hi = c["P3_mean_vertical_over_1361_x_disc_fraction"]
        out.append(("P3", lo <= ratio <= hi, f"ratio {ratio:.4f}"))
    if p["mean_vertical_w_m2"] > 0:
        share = p["mean_horizontal_w_m2"] / p["mean_vertical_w_m2"]
        out.append(("P4", share <= c["P4_mean_horizontal_over_mean_vertical_max"], f"flat/vertical {share:.4f}"))
    if disc == 0:
        out.append(("P5", p["mean_vertical_w_m2"] == 0 and p["peak_vertical_w_m2"] == 0, "no disc, no power"))
    if fr:
        ok = fr["sunrise_utc"] >= start_utc[:19] and (fr["to_full_disc_h"] is None or fr["to_full_disc_h"] > 0)
        out.append(("P6", ok, f"sunrise {fr['sunrise_utc']}, to full disc {fr['to_full_disc_h']}"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=LIVE)
    a = ap.parse_args()
    raw = RULES.read_bytes()
    rules = json.loads(raw)
    if rules.get("status") != "approved_before_run" or not rules.get("approved_by"):
        raise SystemExit("validation/power_tolerances.json is not approved yet: approve it (and push) before the run")
    sha = hashlib.sha256(raw).hexdigest()
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    health = post(a.base, "/api/health")
    q, c = rules["requests"], rules["criteria"]
    started = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    results, all_ok = [], True
    for at in q["at_utc"]:
        resp = post(a.base, "/api/compare", {"places": [{"site_id": s} for s in q["places"]], "at_utc": at,
                                             "days": q["days"], "panel_height_m": q["panel_height_m"]})
        for row in resp["rows"]:
            checks = check_row(row, c, at)
            ok = all(x[1] for x in checks)
            all_ok &= ok
            results.append({"at_utc": at, "site": row["key"], "terrain_m": (row.get("terrain") or {}).get(
                "finest_resolution_m"), "sun_disc_percent": row["period"].get("sun_disc_percent"),
                "power": row["period"].get("power"), "checks": checks, "ok": ok})
    verdict = "PASS" if all_ok else "FAIL"
    day = started[:10]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"power_check_{day}.json").write_text(json.dumps({
        "gate": rules["gate"], "verdict": verdict, "run_utc": started, "commit": commit,
        "server": a.base, "api_version": health.get("api_version"), "rules_sha256": sha,
        "rules_status": rules["status"], "results": results}, indent=2) + "\n")
    lines = [f"# Gate P: sunlight power on real data — {verdict}", "",
             f"Run {started}, commit {commit}, server {a.base} (API {health.get('api_version')}). "
             f"Rules `validation/power_tolerances.json` (sha256 {sha[:16]}…, predeclared {rules['predeclared_utc']}, "
             f"approved by {rules['approved_by']}).", "",
             rules["what_this_is_not"], "",
             "| Date (30 d) | Site | Terrain | Disc % | Mean vertical W/m² | Mean flat W/m² | kWh/m² | Partial Sun % "
             "| First sunrise → full disc | Checks |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        p = r["power"] or {}
        fr = p.get("first_sunrise")
        rise = "—" if not fr else (f"{fr['sunrise_utc'][:16]}Z, " + (
            "sets first" if fr.get("set_before_full_disc") else
            f"{'≥ ' if fr['lower_bound'] else ''}{fr['to_full_disc_h']:.1f} h"))
        marks = " ".join(f"{k}:{'ok' if ok else 'FAIL'}" for k, ok, _ in r["checks"])
        lines.append(f"| {r['at_utc'][:10]} | {r['site']} | {r['terrain_m']} m | {r['sun_disc_percent']:.1f} | "
                     f"{p.get('mean_vertical_w_m2', 0):.0f} | {p.get('mean_horizontal_w_m2', 0):.1f} | "
                     f"{p.get('energy_vertical_kwh_m2', 0):.0f} | {p.get('partial_sun_percent', 0):.0f} | {rise} | {marks} |")
    lines += ["", "Details of every check are in the .json.", ""]
    (EVIDENCE / f"power_check_{day}.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
