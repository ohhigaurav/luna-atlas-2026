# Backend calls for the new 3D app

For whoever builds `frontend/app`. Use these five calls. The expert endpoints (`/api/analysis`,
`/api/finder`) stay available for the expert drawer, but a visitor should never see their settings.

| need | call |
|---|---|
| sites for the globe pins | `GET /api/reference-sites` (official sites at `GET /api/sites` from 13 Nov) |
| Sun/Earth direction for lighting the globe | `POST /api/sky-geometry` `{start_utc, end_utc, step_min}` |
| **"When can I land here?"** (the main question) | `POST /api/landing-windows` `{site_id, search_start_utc, search_days, mission_days}` |
| **"Check this site"** for a chosen date | `POST /api/check` `{site_id, start_utc, days, panel_height_m}` |
| full time series for the surface sky view and time dock | `GET /api/runs/{run_id}` (the check returns `run_url`) |

## `POST /api/check`

Request: `site_id` (required); `start_utc` (ISO, must end in `Z`); `days` (1 to 60, default
30); `panel_height_m` (0 to 10, default 2). Nothing else is accepted. The server chooses terrain
or flat, the time step and the precision, and reports its choices in `chosen_settings`.

Response (abridged):

```json
{
  "kind": "site_check",
  "site": {"site_id": "...", "name": "...", "latitude_deg": -89.45, "longitude_deg": 222.69},
  "chosen_settings": {"horizon_mode": "terrain", "coarse_step_min": 30, "event_tolerance_s": 10,
                      "sun_observer_height_m": 2, "antenna_height_m": 2, "why": "..."},
  "summary": {
    "headline": "Sunlight reaches a panel 2 m above the ground 61% of the time. Earth is above ...",
    "lines": ["...", "Longest stretch of darkness: 11 d 19 h.", "..."],
    "numbers": {"sunlit_percent": 60.6, "earth_percent": 60.8, "both_percent": 39.8},
    "limits": {"source": "default mission profile ...", "all_pass": false,
               "checks": [{"key": "darkness", "label": "Longest darkness", "text": "11 d 19 h",
                           "value_h": 283.7, "limit_h": 50, "status": "fail", "lower_bound": false}]},
    "bands": {"sun": [{"start_utc": "...", "end_utc": "..."}], "earth": [...]},
    "terrain_status": "terrain-verified",
    "caveats": ["Reference site from published sources, ...", "..."]
  },
  "run_id": "...", "run_url": "/api/runs/...",
  "cache_hit": false, "compute_seconds": 12.3
}
```

How to show it:
* The **headline** is the result card's first line. **lines** come next.
* Each **limits.checks** entry is a chip: `pass` green, `fail` red, `unknown` grey. `unknown`
  means a lower bound: the check window cut the outage, so it may be longer than shown.
* **bands** are the time dock's sunlight and Earth stripes.
* **caveats** are always visible, small, under the result. Never hide them.
* Mast slider: call `/api/check` with `panel_height_m` 0, 1, 2, 5 and 10. Repeats are served from
  the run cache (`cache_hit: true`), so moving the slider back is instant.

Errors: 422 = bad input (`detail` is a list from validation or a string); 503 = the backend is
not configured (no kernels). Show the message; never fall back to made-up numbers.

Responses are gzip-compressed when the browser accepts it.

## `POST /api/landing-windows`

Request: `site_id`, `search_start_utc` (ending in `Z`). Optional, with these defaults:
`search_days` 90 (max 180), `mission_days` 10, `panel_height_m` 2,
`require_earth_at_landing` true, `max_sun_elevation_deg` 20 (null turns that rule off).

Response (abridged):

```json
{
  "kind": "landing_opportunities",
  "summary": ["Next landing opportunity at Apollo 11: touch down between 2027-01-14 06:00 and 2027-01-17 12:00 UTC. Landing at ... gives 13.2 days of sunlight; Earth is in view 100% of the mission."],
  "opportunities": [{"touchdown_from_utc": "...", "touchdown_until_utc": "...", "best_touchdown_utc": "...",
                     "daylight_after_best_h": 317.0, "daylight_is_lower_bound": false, "sunset_utc": "...",
                     "sun_elevation_at_best_deg": 1.2, "earth_in_view_during_mission_pct": 100.0}],
  "opportunity_count": 3,
  "closest_miss": null,
  "candidates_failing": {"sun_up": 2100, "daylight": 1650, "earth_up": 0, "low_sun": 900},
  "longest_sunlit_window": {"start_utc": "...", "end_utc": "...", "hours": 341.2, "is_lower_bound": false},
  "rules": {"mission_days": 10, "text": {"sun_up": "Sun above the horizon at touchdown", "...": "..."}},
  "horizon_mode": "flat",
  "caveats": ["..."]
}
```

When there are no opportunities, `closest_miss` says which rules failed and by how much, and
`summary` explains it ("It would give 9.1 days of sunlight; you asked for 10."). Never show a bare
"not possible": show the summary, the closest miss and the rule chips.
