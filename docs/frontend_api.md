# Backend calls for the new 3D app

For whoever builds `frontend/app`. Use these five calls. The expert endpoints (`/api/analysis`,
`/api/finder`) stay available for the expert drawer, but a visitor should never see their settings.

| need | call |
|---|---|
| sites for the globe pins | `GET /api/reference-sites` (official sites at `GET /api/sites` from 13 Nov) |
| Sun/Earth direction for lighting the globe | `POST /api/sky-geometry` `{start_utc, end_utc, step_min}` |
| **"When can I land here?"** (the main question) | `POST /api/landing-windows` `{site_id, search_start_utc, search_days, mission_days}` |
| **"Check this site"** for a chosen date | `POST /api/check` `{site_id, start_utc, days, panel_height_m}` |
| **compare 2–6 sites/points side by side** (challenge core) | `POST /api/compare` `{places, at_utc, days}` |
| **slope over a landing ellipse** (5 m terrain only; no dates, no SPICE) | `POST /api/slope` `{site_id, semi_major_m, slope_limit_deg}` |
| full time series for the surface sky view and time dock | `GET /api/runs/{run_id}` (the check returns `run_url`) |

## `POST /api/slope`: ground slope in the landing ellipse (new 7 Nov, D-23; challenge C11)

Request: `site_id`, or `latitude_deg` + `longitude_deg` (clicked point). Optional: `semi_major_m` 250
(25–1500), `semi_minor_m` (default = round), `orientation_deg` 0 (bearing of the major axis), `spacing_m`
(default = the ellipse view's, so `points` line up with `/api/landing-ellipse` points), `slope_limit_deg`
8 (0.5–45). No SPICE and no dates. Measured on a development laptop (8 Nov, Sites 001/004): 0.3 s at 250 m and
0.6 s at 1500 m once the rasters are hash-checked (~1 s the first call per process). Debounce re-asks on
limit changes; the CDF covers the instant update.

Response (`status: "ok"`):

- `label`: show it under every slope number, verbatim: "Slope of the 5 m LOLA terrain, 10 m baseline
  (3×3 Horn). Not a hazard certification: …".
- `limit_deg`, `limit_note` (the 8° default is an example, not a lander requirement; say so next to the input).
- `area`: over every 5 m pixel inside the ellipse. `slope_deg.{median,p90,p99,max}`, `share_within_limit`,
  `share_over_limit`; with the error layer staged also `share_clearly_within`, `share_uncertain`,
  `share_clearly_over`. `cdf.share_at_or_below[i]` = share of the ellipse with slope ≤ `i × 0.5`°.
- `points[]`: `east_m`, `north_m`, `slope_deg`, `slope_err_deg` (null if no error layer), `slope_verdict`
  `within` / `over` / `uncertain` / null.
- `overlay`: `max_slope_deg[row][col]`, rows north → south, columns west → east, cell `cell_m`, first cell
  centre at (`first_cell_centre_east_m`, `first_cell_centre_north_m`), local east/north metres from the
  target (same frame as the ellipse points). Each cell is the **steepest** pixel in it; null = outside or unknown.
- `chips`: e.g. `["target 3.1°", "typical 4.2°", "steepest 18°", "82% of ellipse ≤ 8°"]`.
- `terrain.native_resolution_m` (always ≤ 5), `uncertainty.available`, `validation` (`status: "pass"`
  since 8 Nov, with `summary`, `evidence`, `scope`), `compute_seconds`.

`status: "not_available"` + `reason` (HTTP 200) where no 5 m tile covers the whole ellipse (Malapert,
equatorial sites, ellipses past the tile edge). Show the reason; never fall back to anything else.

**Ellipse timing (measured 8 Nov, a development laptop, 14 days, Sites 001/004, 100–1000 m):** 234–315 s per
ellipse the first time (each point is a full 5 m terrain analysis), instant from the cache after. Live, show
the job's progress and elapsed time and never block other panels on it; static mode has the 8 baked ellipses.

`POST /api/landing-ellipse` now also carries slope (schema 1.1): each point has `slope_deg`,
`slope_err_deg`, `slope_verdict` at the default 8°, and `slope` has `area`, `overlay`, `chips` and
`best_sunlit_within_limit` (`east_m`, `north_m`, `sunlit_percent`, `dte_clear_percent`, `slope_deg`, or null).
If `slope.status` is not `ok`, draw the ellipse as before. For the user's own limit: recolour points from
`slope_deg`, read the area share from `area.cdf`, and pick the best flat-enough point client-side
(highest `sunlit_percent` among points with `slope_deg ≤ limit`), or call `/api/slope`. Static mode has
the baked ellipses only, so use the CDF there.

### Handoff for the frontend session (paste as is)

> Backend 0.7.41 adds slope to the landing ellipse (docs/frontend_api.md → `POST /api/slope`).
> In the polar site panel's Landing ellipse:
> 1. A "Slope" toggle beside the sunlight colouring. On: colour each point by `slope_deg` against the
>    limit (within / uncertain / over; never colour alone, add the number on hover) and draw `slope.overlay`
>    as a faint heat layer under the points (steepest-in-cell, say so in the legend).
> 2. A "Lander slope limit" number input (default 8°, step 0.5) with `limit_note` as helper text. Changing
>    it updates the chips from `area.cdf` immediately and re-asks `/api/slope` (debounced) when live.
> 3. One new chip next to the sunlight chips: "{share}% of ellipse ≤ {limit}°", and the marker
>    "best sunlit spot under {limit}°" from `best_sunlit_within_limit` (or from the points for a custom limit),
>    shown beside the existing best point when they differ. That pair is the demo beat: the sunniest spot
>    may be too steep.
> 4. Under the slope numbers always show `label` verbatim and "5 m terrain". When `slope.status` is
>    `not_available`, show the reason in one grey line and no slope controls.
> 5. Evidence screen: a "Slope (Gate S) — PASS" row: "Matches NASA's published slope maps at Sites 001
>    and 004: 95% of pixels within 0.7° / 0.9°" with a link to `validation.evidence`. Under the slope numbers:
>    "checked against NASA's slope map" (a link) next to the label; never "safe".
> Do not show slope for clicked points outside the 5 m tiles, and never call it "safe" or "hazard-free".

## `POST /api/sky-geometry`: stars and Earth's face (new 6 Nov)

Two fields were added to `series`; everything else is unchanged.

- **`series.j2000_to_frame`**: one row-major 3×3 matrix per sample, SPICE
  `pxform("J2000", "MOON_ME", et)`.
  - For a star at J2000 RA α, Dec δ, take `v = [cos δ cos α, cos δ sin α, sin δ]` and draw it at
    `M @ v`. This is the same Moon-fixed frame as the Sun and Earth vectors.
  - Stars are at infinity, so no observer offset applies.
  - Stellar aberration (up to 20″) is not applied.
  - In three.js, put the rows into a `Matrix3` with `.set(m[0][0], m[0][1], m[0][2], m[1][0], …)`
    and apply it to the star-field group. Between samples, slerp or just step: the Moon turns about
    0.27° per 30 min.
- **`series.earth.sub_moon_lat_deg` / `sub_moon_lon_east_deg`** (`sub_moon_frame: "IAU_EARTH"`):
  the point on Earth where the Moon is overhead, so it is the centre of the face Earth shows the
  Moon.
  - Rotate the Earth texture so this lat/lon faces the camera on the Moon.
  - Latitude is planetocentric (map latitude differs by ≤ 0.19°, invisible at globe size).
  - It moves west about 15° per hour, so interpolate the longitude with wrap at 360.

Checked by `tools/check_sky_orientation.py`: orthonormal matrices, agreement with SPICE vectors, the
Moon's pole and spin rate, and the sub-Moon point vs JPL Horizons. The limits were fixed before
the first run. Until that run passes, label Earth's face "illustrative".

## Any point on the Moon (new 6 Nov)

`/api/landing-windows` and `/api/check` accept a clicked point instead of a site:

```json
{"latitude_deg": -89.38, "longitude_deg": 201.5, "search_start_utc": "2027-01-01T00:00:00Z"}
```

- Send either `site_id`, or `latitude_deg` and `longitude_deg`. Sending both, or neither, is a 422.
- Latitude is planetocentric. Longitude is east, in −180 to <360; it is folded to [0, 360) and
  rounded to 1e-6°.
- The response's `site` is `{"site_id": "custom-point", "origin": "custom", "name": "Point 89.380° S,
  201.500° E", ...}`.
- Terrain comes from the 240 m regional map only (no 5 m tiles), and a caveat says so. Outside the
  regional map, the response falls back to a flat horizon with its note, as for catalogue sites.
- Results are cached per point. The first answer for a new point takes as long as for a site
  (seconds to about a minute for 90 days); a repeat is instant.
- Suggested UI: click → drop a pin → ask landing windows. Show the caveat chip "240 m terrain".

## "Verify with NASA JPL ↗" (new 6 Nov)

- `/api/check` returns `verify`, for the first sample of the run.
- `/api/landing-windows` returns `verify` on each opportunity (at `best_touchdown_utc`) and on
  `closest_miss`.

```json
"verify": {"utc": "2027-01-03T14:00:00Z", "note": "...",
  "sun":   {"ours_azimuth_deg": 151.2, "ours_elevation_deg": 1.83, "observer_altitude_m": 1952.0,
            "horizons_url": "https://ssd.jpl.nasa.gov/api/horizons.api?format=text&..."},
  "earth": {...}}
```

Suggested UI: a small "Verify with NASA JPL ↗" link next to the Sun height. It opens
`horizons_url` in a new tab: JPL's own plain-text table for that point and second. Next to the
link, show "ours: 1.83°" so a judge can compare the two numbers. Horizons has no lunar hills,
so the matching numbers are the sky position above the level horizon, not sunrise times; `note`
says this in one line.

## `GET /api/site-index`: every site, official first (new 6 Nov; needed from 13 Nov)

`{"official_state": "awaiting_official_source" | "loaded", "official_count": 0, "reference_count": 27,
  "sites": [...official (origin "official", kind "official_challenge_site", group "Official challenge sites")...,
            ...reference (origin "reference")...], "unplaced_official": [], "note": "..."}`

Static bundle: `data/site-index.json`. Until 13 Nov it holds the reference points only.

Some sites carry `analysis_note: {text, evidence, suggested_point?}`: our measured findings, kept
apart from the citation. Show the text in the site panel under the name, in small type, with an
"evidence" link. If `suggested_point` is present, add a button "Try {label}" that opens that
point as a clicked point. Malapert: its published point gets 0% Earth, and the button opens the
crest, which gets 70%. That is the challenge's "small location changes matter" in one click. **Switch
the site loader to this now** (fall back to `/api/reference-sites`), so the official sites appear
on event day without a code change. Labels and banner: an internal document (not published) → Frontend.

## Landing rule R5, minimum Sun height (new 6 Nov)

`/api/landing-windows` takes `min_sun_elevation_deg`: `"auto"` (default), a number, or `null`
(off).
- **auto** = 5° where the Sun can climb past 14°. That is Apollo's lower bound (Apollo landed with
  the Sun 5–14° up). It covers every site within 77.5° of the equator. Near the poles the Sun never
  gets that high, so R5 is off there.
- The response's `rules.min_sun_elevation_deg` is the value used (`null` = off), and
  `rules.min_sun_reference` gives the sources.
- A miss caused by it shows as `sun_high` in `closest_miss.failed_rules`. Text: "Sun high enough to
  light the ground".
- **Effect:** the Apollo 11 site no longer offers "best touchdown with the Sun at −0.22°". Its best
  touchdown now has the Sun at 5° or higher.
- Each opportunity also has `sun_above_horizon_at_best_deg`: the Sun's height above the **local
  horizon**, as opposed to `sun_elevation_at_best_deg`, its height above the level horizontal.
  They differ on ridges and summits. At the Malapert crest the Sun is at −2.9° from the level
  horizontal but above the dipped horizon of a 5 km peak. Show "Sun 1.2° above the horizon" as
  the main number and the level-horizontal elevation as a detail. `closest_miss` has
  `sun_above_horizon_deg`.
- The frontend need not send anything; to expose it, add "Min Sun height: auto / 0° / 5° / 10°"
  to the landing settings.

## `POST /api/compare`: sites and dates side by side (new 6 Nov; challenge core)

```json
{"places": [{"site_id": "reference-lola-site-001"}, {"site_id": "reference-lola-site-004"},
            {"latitude_deg": -89.45, "longitude_deg": 223.2}],
 "at_utc": "2027-01-10T00:00:00Z", "days": 30, "panel_height_m": 2}
```

Send 1–6 places: catalogue sites or clicked points. Each runs the cached one-button check, so
repeated questions are instant. Response:

```json
{"kind": "site_comparison", "at_utc": "...", "days": 30,
 "rows": [{"key": "reference-lola-site-001", "site": {...}, "horizon_mode": "terrain",
   "now": {"sun": {"up": true, "elevation_deg": 1.21, "azimuth_deg": 312.4, "horizon_deg": 0.35},
           "earth": {"up": true, "elevation_deg": 2.9, "azimuth_deg": 2.1, "horizon_deg": 0.8}},
   "sun_next":   {"up": true,  "event": "sunset",   "utc": "...", "in_h": 412.5, "lower_bound": false},
   "earth_next": {"up": true,  "event": "earthset", "utc": "...", "in_h": 330.0, "lower_bound": false},
   "period": {"sunlit_percent": 98.0, "earth_percent": 47.0, "both_percent": 46.0,
              "longest_darkness_h": 12.0, "longest_darkness_lower_bound": false,
              "longest_earth_gap_h": 360.0, "longest_earth_gap_lower_bound": true,
              "sun_disc_percent": 91.2,
              "power": {"mean_vertical_w_m2": 1201.0, "mean_horizontal_w_m2": 31.0,
                        "peak_vertical_w_m2": 1318.4, "energy_vertical_kwh_m2": 865.0,
                        "partial_sun_percent": 14.0, "step_h": 0.5, "solar_constant_w_m2": 1361.0,
                        "first_sunrise": {"sunrise_utc": "...", "full_disc_utc": "...", "to_full_disc_h": 9.5,
                                          "lower_bound": false, "full_disc_reached": true,
                                          "peak_disc_percent": 100.0, "resolution_h": 0.5},
                        "definition": "...", "not_included": "..."}},
   "limits_all_pass": false,
   "limits": [{"key": "darkness", "label": "Longest darkness", "value_h": 310.0, "limit_h": 50.0,
               "text": "12 d 22 h", "lower_bound": false, "status": "fail"}, ...],
   "caveats": [...], "verify": {...}, "run_id": "..."}],
 "leaders": {"most_sunlight": ["reference-lola-site-001"], "longest_until_earthset": [...], ...}}
```

- `sun_next` / `earth_next` give the **time to sunset or sunrise, and to Earthset or
  Earthrise**. The challenge asks for these by name.
- `lower_bound: true` means the event is beyond the analysed days: show "≥ 30 d".
- `none_in_period: true` means it never rises in the period.
- `leaders` names the best key per metric; ties are listed together. There is no combined score.
  Highlight the leader's cell in each row.
- **Sunlight power (0.7.72)** — `period.power`, missing or `null` in older static answers (hide the row then).
  The sunlight reaching a panel at `panel_height_m`, **before panel efficiency** (W/m²):
  `mean_vertical_w_m2` for a vertical panel turned to the Sun (how polar landers mount panels) is the
  headline; `mean_horizontal_w_m2` (flat panel) shows why the Sun's height matters: at the pole it is a few
  percent of the vertical one. `energy_vertical_kwh_m2` is per m² over the analysed days.
  `partial_sun_percent` is the share of time only part of the Sun's disc is above the horizon.
  `first_sunrise`: the first sunrise inside the period (null if none, or if the Sun was already up) and how
  long until the whole disc is clear (`to_full_disc_h`, accurate to `resolution_h`; "at least" when
  `lower_bound`; `set_before_full_disc: true` = the Sun set again first). Labels must say "sunlight on a
  panel, before panel efficiency" and never "power output". Leader key: `most_power`.
- Changing the date or a place means asking again.

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
    "headline": "Some of the Sun is visible from a panel 2 m above the ground 61% of the time; averaged over the whole disc, 55%. Earth is above ...",
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

## Hosting: API address, CORS and the ellipse job (new 8 Nov, 0.7.46)

The hosted app (Cloudflare Pages) and the API (Azure VM) are different origins. The backend allows the
app's origin through `LUNA_CORS_ORIGINS`; the frontend must call the API's full address. See
an internal document (not published).

**`POST /api/landing-ellipse/jobs`** (same body as `POST /api/landing-ellipse`) returns at once:
`{job_id, status: "queued"|"running"|"done"|"error", done, total, queued_s, elapsed_s, error, error_kind}`.
Poll **`GET /api/landing-ellipse/jobs/{job_id}`** every 2–3 s; when `status === "done"` the body has
`result` (exactly the `/api/landing-ellipse` answer). Identical requests share one job (a second
judge asking the same ellipse joins the first). At most 2 ellipses compute at once; others wait as
`queued`. 404 means the server restarted: start the job again. 422 = the request is refused (unknown
or non-polar site) before any job starts. Why: an ellipse takes 4–5 min, and some browsers end a
single HTTP response after 300 s.

`GET /api/live` is the cheap liveness probe (`{status: "ok", version}`); `/api/health` hashes every
kernel and DEM and is slow.

### Handoff for the frontend session: hosted mode (paste as is)

> Backend 0.7.46. The app will be served from Cloudflare Pages and call the API on an Azure VM
> (an internal document (not published)). Two changes:
>
> 1. **API base.** Add `src/api/base.ts`:
>    `export const API = ((import.meta.env.VITE_API_BASE as string | undefined) ?? '').replace(/\/$/, '');`
>    and use `API + path` for every backend call: `post()` and `fetchRun()` in `api/plan.ts`,
>    `api/sky.ts` (`/api/sky-geometry`), `api/compare.ts`, `CompareView.tsx` (`/api/runs/…`),
>    `EllipsePanel.tsx`, and both probes in `data/source.ts` (`/api/site-index`, `/api/reference-sites`).
>    `run_url` values from the backend are relative (`/api/runs/…`): prefix them too. Static-answer
>    keys (`staticAnswers.ts`, `endpointOf`) keep using the bare path. Empty `VITE_API_BASE` (local dev,
>    `run_local.sh`) behaves exactly as today. Add `VITE_API_BASE?: string` to `vite-env.d.ts`.
> 2. **Ellipse as a job.** In live mode `EllipsePanel` starts `POST /api/landing-ellipse/jobs`, polls
>    `GET /api/landing-ellipse/jobs/{id}` every 2.5 s, and shows "Computing live on the server: point
>    {done} of {total} · {elapsed_s} s" (or "Waiting for another ellipse to finish · {queued_s} s" while
>    queued) with a thin progress bar. On `done` render `result` as today. On 404, start again once. On
>    `error`, show `error`. Stop polling when the panel closes. Static mode keeps reading the baked
>    `/api/landing-ellipse` answers unchanged. Under the result: "computed live in {elapsed_s} s"
>    (or "from this server's cache" when `result.cache_hit`).

## `POST /api/landing-windows`

Request: `site_id`, `search_start_utc` (ending in `Z`). Optional, with these defaults:
`search_days` 90 (max 366; the app's presets are 30 / 90 / 180 / 365), `mission_days` 10, `panel_height_m` 2,
`require_earth_at_landing` true, `max_sun_elevation_deg` 20 (null turns that rule off).

**Soonest and best (new 8 Nov, 0.7.42).** Every answer now has, over *all* windows in the search
(not only the first 24 listed in `opportunities`):

- `soonest`: the first window (same fields as an opportunity, plus `verify`), or null;
- `best`: the touchdown that leaves the **most sunlight after landing**; ties go to more Earth in view
  during the mission, then to the earlier date. Same fields plus `rank` (1 = it is also the soonest)
  and `verify`; null when no window exists;
- `best_earth` (new 8 Nov, 0.7.43): the touchdown with the **most Earth in view during the mission**; ties go to
  more sunlight, then earlier. Same fields plus `rank` and `verify`. It differs from `best` often: at Site 001 in
  2027 the sunniest window (20.6 d) has Earth only 11% of the mission, the first one (18.4 d) has 41%;
- `best_rule`: both rules in one sentence, for the small print.

`summary` gains a line: "Best in the period: land at … for 13.2 days of sunlight, Earth in view 87% of
the mission", or "The next opportunity is also the best one in the period". A 365-day search runs about
7 analysis chunks the first time per site and question, then comes from the cache. It has not been timed on real data yet: show the
elapsed seconds while it runs.

### Handoff for the frontend session: best date, mission playback, mission length, origin badge (paste as is)

> Backend 0.7.43: `/api/landing-windows` accepts `search_days` up to 366 and returns `soonest`, `best`
> (most sunlight after touchdown), `best_earth` (most Earth in view during the mission) and `best_rule`.
> Measured on a development laptop: 365 days at Site 001 took 44 s the first time, 0 s from the cache.
> The team's feedback 8 Nov: playback ran from 99% to 0 with no explanation, and the request was "the best possible date,
> whether it is 30, 90, 200 or 365 days".
>
> **A. Best date.**
> 1. In the site card and panel, a small segmented control "Look ahead: 30 d · 90 d · 180 d · 365 d"
>    (default 90). It changes only this question: send `search_days` with it and put it in the
>    `landingRequest` cache key. The ring, calendar and pins keep their 90 / 30 days.
> 2. Two lines, both from the date in the date bar:
>    "Soonest: {soonest.best_touchdown_utc} (in {span from the date bar})" and
>    "Best in the next {N} days: {best.best_touchdown_utc}: {daylight_after_best_h as days} of sunlight,
>    Earth in view {earth_in_view_during_mission_pct}%". When `best.rank === 1`, one line:
>    "Soonest is also the best in the next {N} days". `best_rule` goes in the tooltip.
>    Show the trade-off, not one magic date: "Most sunlight: {best date} · {days} d sun · Earth {pct}%" and
>    "Most Earth contact: {best_earth date} · Earth {pct}% · {days} d sun". Collapse lines that point at the
>    same window (compare `best_touchdown_utc`).
> 3. Buttons: "Go to best" (jumps the date bar) and "Play the mission from here" (opens the 3D ground
>    view at `best.best_touchdown_utc`).
> 4. While loading: "Searching the next {N} days… {elapsed} s". In static mode, keep 90 d only and grey
>    the others with "needs the live backend".
> 5. SitePanel's `formatIn(answer.inDays)` counts from `Date.now()`, while the card counts from the date
>    bar. Make both count from the date bar.
>
> **B. Mission playback.** The drain happens because "Stand here in 3D" on the SiteCard opens at the
> date bar's moment (`onStand(cursorMs)`), not at a landing window. If the Sun is down or behind a ridge,
> the panel makes 0 W and the 2 kWh battery at 60 W is empty in ~33 h with nothing else happening.
> 1. "Stand here in 3D": if the date bar is inside a window, start there. Otherwise start at the next
>    window's best touchdown, with a one-line note: "Starting at the next landing window, {date}". If there
>    is none in the look-ahead, open at the date bar with: "No landing window in the next {N} days: this
>    shows the lander waiting in the dark."
> 2. A live status line under the battery, from the run's series: "Charging: Sun 1.8° up, panel 380 W,
>    using 60 W" / "Draining: Sun behind the hills (rises in 9 h)" / "Night: battery lasts {h} more at
>    {loadW} W, sunrise in {h}" (the latter "no sunrise in these 30 days" when none).
> 3. A thin battery-charge curve over the 30 days (from `simulate().socWh`) with the sunlit bands behind
>    it and a marker where it empties, so 99% → 0 has a visible reason before you press play.
> 4. Keep "illustrative power model" on screen. Panel, battery and load are the player's choices.
>
> **C. Mission length on the card** (team feedback). The
> −/+ control exists only in the expanded SitePanel. Put it on the SiteCard verdict as chips:
> `Mission: 1 d · 3 d · 5 d · 7 d · 10 d · 14 d` (current one highlighted, same `onSettings({ missionDays })`),
> right under "You can land on this date" / "Not a good date to land here". Make the sentence say it:
> "Land by then and the Sun stays up for **{N} days** (your mission)". The backend accepts 0.25–30 days;
> keep the app's 1–14 clamp.
>
> **D. Origin badge** ("Reference site, not official" reads like an apology). Say where the
> coordinates come from instead; the "not from the challenge list" part moves to the tooltip. Replace
> `originLabel` in `SiteCard.tsx` and use `originTitle` as the `title` of both badges (SiteCard, SitePanel):
>
> ```ts
> const SOURCE_NAMES: Array<[RegExp, string]> = [
>   [/lroc/i, 'LROC'], [/nssdc/i, 'NASA NSSDC'], [/10\.3847\/psj|\/psj\//i, 'Planetary Science Journal'],
>   [/usgs/i, 'USGS gazetteer'], [/science\.nasa\.gov/i, 'NASA'], [/ncbi|pmc/i, 'peer-reviewed study'],
> ];
> const sourceName = (s: ReferenceSite) => SOURCE_NAMES.find(([re]) => re.test(s.source_url ?? ''))?.[1];
>
> /** Where the coordinates come from, always in words (an internal document (not published)). */
> export function originLabel(site: ReferenceSite): string {
>   if (site.site_id.startsWith('point:')) return 'Your point';
>   if (site.origin === 'official') return 'Official challenge site';
>   const src = sourceName(site), from = src ? ` · ${src}` : '';
>   if (site.position_kind === 'landed_hardware') return `Landing site${from}`;
>   if (site.position_kind === 'target_region_centre') return `Planned target, region centre${from}`;
>   return `Published site${from}`;
> }
> export function originTitle(site: ReferenceSite): string {
>   if (site.site_id.startsWith('point:')) return 'A point you picked on the map.';
>   if (site.origin === 'official') return 'From the Space Apps 2026 challenge site list.';
>   const src = sourceName(site);
>   return `Coordinates from ${src ?? 'a published source'}${site.source_record ? ` (${site.source_record})` : ''}. ` +
>     "Not from the challenge's own site list, which is released 13 Nov and marked \"Official challenge site\".";
> }
> ```
>
> Result: "Landing site · LROC" (Chandrayaan-3, IM-1, Chang'e, SLIM), "Landing site · NASA NSSDC"
> (Apollo), "Published site · Planetary Science Journal" (LOLA 001/004), "Planned target, region
> centre · USGS gazetteer" (IM-3). Keep the App.tsx footer line (~429) as is: the honesty stays one hover away.

Cached (5 Nov): an identical request with the same software, horizon algorithm and kernel/DEM
manifests is answered from `data/cache/landing/` with `"cache_hit": true`. The app asks this for
every site on opening (green pins), so the first opening is slow and later ones are instant.

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
