#!/usr/bin/env python3
"""Gate D: do our dates and Sun/Earth positions match what real missions experienced?

Gate B compared our geometry with JPL Horizons, another computation. This gate compares the
production analysis (the same code as /api/analysis and /api/check) with independent references
from real missions: when landers actually saw the Sun set or rise, and the Sun/Earth positions
NASA's Apollo Lunar Surface Journal lists for the Apollo landings. Pass rules were fixed here,
2026-11-02, before the first run. A FAIL is reported as a FAIL.

Cases and pass rules
--------------------
D1 Blue Ghost Mission 1 (Mare Crisium, flat horizon; no DEM north of 60 S).
   Reference: landed 2025-03-02 08:34 UTC and reported 346 hours of daylight, which puts sunset
   at about 18:34 UTC on 16 Mar 2025; last contact 23:25 UTC "about 5 hours after sunset" puts it
   at about 18:25 UTC. PASS if the Sun is up at landing and the modelled sunset (upper limb) is
   within 2 h of 18:30 UTC, 16 Mar 2025. 2 h covers the rounding in "346 hours" and "about
   5 hours", plus about 1 deg of real horizon relief that the flat model omits.
D2 SLIM (near Shioli crater, flat horizon).
   Reference: landed 2024-01-19 15:20 UTC; JAXA and press reports say the Sun set on SLIM on
   31 Jan / 1 Feb 2024 and it went dormant. PASS if the Sun is up at landing and the modelled
   sunset is between 2024-01-31 00:00 and 2024-02-02 00:00 UTC.
D3 Chandrayaan-3 (69.37 S, terrain horizon).
   Reference: ISRO expected the next sunrise at the site around 22 Sep 2023 ("from 20 September
   onwards"); reports put nightfall around 4 to 6 Sep 2023. PASS if the modelled sunset is between
   2023-09-03 00:00 and 2023-09-07 00:00 UTC and the next sunrise between 2023-09-19 00:00 and
   2023-09-23 00:00 UTC. These are planning statements, not observed events, so this is the
   weakest case.
D4 Apollo 11, 14, 15 at landing (flat; these values are geometric).
   Reference: Apollo Lunar Surface Journal, "Sun and Earth: Altitudes and Azimuths at the Apollo
   Landing Sites" (Fjeld and Scotti). PASS if Sun and Earth altitude and azimuth are each within
   0.3 deg. 0.3 deg covers their slightly different site coordinates (up to ~400 m) and unknown
   ephemeris. This is an independent computation, not an observation.
All runs: observer 2 m (roughly lander deck/panel height), 30 min step, 10 s event precision.
D5 Chang'e-4 (far side): no direct line of sight to Earth, which is why China launched the
   Queqiao relay. PASS if Earth's centre stays below the horizon for all of January 2019.

    .venv/bin/python tools/check_mission_events.py
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

H = timedelta(hours=1)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def sunset_and_next_sunrise(site: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    """End of the Sun window that is open at the start, and the start of the next one."""
    windows = site["sun_windows"]
    first = next((w for w in windows if w["start_truncated"]), None)
    sunset = utc(first["end_utc"]) if first and not first["end_truncated"] else None
    later = [w for w in windows if not w["start_truncated"]]
    if sunset is not None:
        later = [w for w in later if utc(w["start_utc"]) > sunset]
    sunrise = utc(later[0]["start_utc"]) if later else None
    return sunset, sunrise


def within(value: datetime | None, lo: datetime, hi: datetime) -> bool:
    return value is not None and lo <= value <= hi


def ang_diff(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


APOLLO = {  # ALSJ landing rows: UTC, Sun alt, Sun az, Earth alt, Earth az
    "reference-apollo-11": ("1969-07-20T20:17:39Z", 10.65, 88.81, 59.43, 272.16),
    "reference-apollo-14": ("1971-02-05T09:18:13Z", 10.36, 89.54, 66.10, 96.70),
    "reference-apollo-15": ("1971-07-30T22:16:29Z", 12.05, 95.73, 69.28, 203.00),
}


def main() -> int:
    from lunar_core.analysis_service import run_analysis
    from lunar_core.api_models import AnalysisRequest

    def run(site_id: str, start: str, days: float, mode: str) -> dict[str, Any]:
        s = utc(start)
        result = run_analysis(AnalysisRequest(
            site_ids=[site_id], start_utc=s, end_utc=s + timedelta(days=days), coarse_step_min=30,
            event_tolerance_s=10.0, horizon_mode=mode, sun_observer_height_m=2.0, antenna_height_m=2.0))
        return result["sites"][0] | {"run_id": result["run_id"]}

    rows: list[dict[str, Any]] = []

    def record(case: str, ok: bool, detail: str, run_id: str) -> None:
        rows.append({"case": case, "pass": ok, "detail": detail, "run_id": run_id})
        print(f"{'PASS' if ok else 'FAIL'}  {case}: {detail}", flush=True)

    s = run("reference-clps-blue-ghost-1", "2025-03-02T08:34:00Z", 16, "flat")
    sunset, _ = sunset_and_next_sunrise(s)
    target = utc("2025-03-16T18:30:00Z")
    up = s["series"][0]["sun_elevation_deg"] > 0
    record("D1 Blue Ghost 1 sunset", up and within(sunset, target - 2 * H, target + 2 * H),
           f"Sun at landing {s['series'][0]['sun_elevation_deg']:.2f} deg; model sunset {sunset} "
           f"vs ~2025-03-16 18:30 UTC ({(sunset - target).total_seconds() / 3600:+.2f} h)" if sunset else
           f"no sunset found; Sun at landing {s['series'][0]['sun_elevation_deg']:.2f} deg", s["run_id"])

    s = run("reference-intl-slim", "2024-01-19T15:20:00Z", 16, "flat")
    sunset, _ = sunset_and_next_sunrise(s)
    up = s["series"][0]["sun_elevation_deg"] > 0
    record("D2 SLIM sunset", up and within(sunset, utc("2024-01-31T00:00:00Z"), utc("2024-02-02T00:00:00Z")),
           f"Sun at landing {s['series'][0]['sun_elevation_deg']:.2f} deg; model sunset {sunset} "
           "vs 31 Jan to 1 Feb 2024", s["run_id"])

    for mode in ("terrain", "flat"):
        s = run("reference-intl-chandrayaan-3", "2023-08-30T00:00:00Z", 32, mode)
        sunset, sunrise = sunset_and_next_sunrise(s)
        ok = within(sunset, utc("2023-09-03T00:00:00Z"), utc("2023-09-07T00:00:00Z")) and \
            within(sunrise, utc("2023-09-19T00:00:00Z"), utc("2023-09-23T00:00:00Z"))
        detail = f"model sunset {sunset}, next sunrise {sunrise} vs sunset 3-6 Sep, sunrise 19-22 Sep 2023"
        if mode == "terrain":
            record("D3 Chandrayaan-3 sunset and sunrise (terrain)", ok, detail, s["run_id"])
        else:
            print(f"info  D3 same with flat horizon (not scored): {detail}", flush=True)

    for site_id, (when, sun_alt, sun_az, earth_alt, earth_az) in APOLLO.items():
        s = run(site_id, when, 0.5, "flat")
        r = s["series"][0]
        diffs = {"sun_alt": abs(r["sun_elevation_deg"] - sun_alt), "sun_az": ang_diff(r["sun_azimuth_deg"], sun_az),
                 "earth_alt": abs(r["earth_elevation_deg"] - earth_alt),
                 "earth_az": ang_diff(r["earth_azimuth_deg"], earth_az)}
        record(f"D4 {site_id.removeprefix('reference-')} at landing", all(v <= 0.3 for v in diffs.values()),
               f"Sun {r['sun_elevation_deg']:.2f}/{r['sun_azimuth_deg']:.2f} vs {sun_alt}/{sun_az}; "
               f"Earth {r['earth_elevation_deg']:.2f}/{r['earth_azimuth_deg']:.2f} vs {earth_alt}/{earth_az}; "
               f"max diff {max(diffs.values()):.3f} deg", s["run_id"])

    s = run("reference-intl-change-4", "2019-01-01T00:00:00Z", 31, "flat")
    top = max(r["earth_elevation_deg"] for r in s["series"])
    record("D5 Chang'e-4 never sees Earth", top < 0, f"highest Earth elevation in Jan 2019: {top:.2f} deg", s["run_id"])

    passed = sum(r["pass"] for r in rows)
    print(f"\n{passed}/{len(rows)} cases pass")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "data" / "derived" / f"mission_events_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"created_utc": stamp, "cases": rows}, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
