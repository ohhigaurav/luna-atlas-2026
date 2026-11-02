# Backend calls for the new 3D app

For whoever builds `frontend/app`. Use these four calls. The expert endpoints (`/api/analysis`,
`/api/finder`) stay available for the expert drawer, but a visitor should never see their settings.

| need | call |
|---|---|
| sites for the globe pins | `GET /api/reference-sites` (official sites at `GET /api/sites` from 13 Nov) |
| Sun/Earth direction for lighting the globe | `POST /api/sky-geometry` `{start_utc, end_utc, step_min}` |
| **"Check this site"** (the one button) | `POST /api/check` `{site_id, start_utc, days, panel_height_m}` |
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
