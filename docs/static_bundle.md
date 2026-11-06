# Static judge bundle

Judges open a link. They will not clone the repo, download ~300 MB of DEMs and kernels, or run
Python, and judging continues for weeks after the hackathon. So the submitted website is the 3D
app built with **precomputed data and no backend**. The live backend remains the way to run other
dates, custom points and settings (`./scripts/run_local.sh`).

## Build

```
.venv/bin/python tools/bake_static.py          # writes frontend/app/public/data/
cd frontend/app && npm run textures && npm run build
```

`dist/` is then a complete static site: the app, `textures/` and `data/`. Deploy that folder
to Cloudflare Pages, Vercel or GitHub Pages. `public/data/` is git-ignored (tens of MB of JSON);
bake it on the machine that has the kernels and DEMs, then deploy from there.

Default bake: window 2027-01-01 to 2027-01-31 at 30 min. Sites at or south of 60 S get terrain
runs at Sun observer heights 0, 1, 2, 5 and 10 m (the F16 mast slider), with the antenna at 2 m.
Other sites get one flat run at 2 m (no DEM north of 60 S, D-22). Runs are one site each. The bake
is resumable: rerunning skips runs already baked with the same settings.

## Format (for the frontend data layer)

Every data file is an **unmodified API response**, so live and static mode share one set of
types and one code path. Only the fetch differs:

| file | same as |
|---|---|
| `data/reference-sites.json` | `GET /api/reference-sites` |
| `data/sky.json` | `POST /api/sky-geometry` for the bundle window |
| `data/runs/<run_id>.json` | `POST /api/analysis` with one site |
| `data/manifest.json` | index (below) |

`manifest.json`:

```json
{
  "schema_version": "1.0",
  "kind": "luna_atlas_static_bundle",
  "generated_utc": "...", "software_version": "...", "git_commit": "... or null",
  "kernel_manifest_sha256": "...",
  "settings": {"start_utc": "...", "end_utc": "...", "step_min": 30,
               "heights_m": [0, 1, 2, 5, 10], "flat_height_m": 2, "antenna_height_m": 2},
  "files": {"reference_sites": "reference-sites.json", "sky": "sky.json"},
  "file_sha256": {"reference_sites": "...", "sky": "..."},
  "run_key_format": "<site_id>|<terrain|flat>|<sun_observer_height_m>m",
  "runs": {
    "reference-lola-site-001|terrain|0m": {"file": "runs/<id>.json", "sha256": "...", "run_id": "...",
      "site_id": "...", "horizon_mode": "terrain", "sun_observer_height_m": 0,
      "sunlit_percent": 0.0, "dte_clear_percent": 0.0}
  },
  "notes": {"<site_id>": "terrain unavailable, flat horizon baked instead: ..."},
  "disclaimer": "..."
}
```

Frontend rules for static mode:

* **Detect mode once.** If `GET /api/health` fails, or the build sets `VITE_STATIC=1`, load
  `data/manifest.json` and use static mode.
* **Pick a run** by key `site|mode|height`. A polar site has terrain keys for every baked
  height. Other sites have only `|flat|2m`. A site listed in `notes` has only a flat run; show
  the note.
* **Disable, don't fake.** Dates outside `settings`, custom points, other heights and the finder
  are unavailable in static mode. Show them disabled, with "Run locally for other dates" and the
  repo link. Never extrapolate or interpolate a run.
* **Show provenance.** The expert drawer shows `generated_utc`, `git_commit` and
  `kernel_manifest_sha256` from the manifest, plus each run's own provenance block.
* **Fetch lazily.** Load `sky.json` and `reference-sites.json` at start. Fetch a run file only
  when its site and height are selected, and cache it.


## Static answers: compare, landing windows, ellipse and ground view without a server (new 6 Nov)

Evaluation runs after 15 Nov for weeks, and no laptop stays on, so the static site must answer
the challenge's core questions by itself. `tools/bake_answers.py` saves the real API responses
the app asks for:

| endpoint | baked for | from |
|---|---|---|
| `/api/landing-windows` | every site, the default question (90 d, 10-day mission, Sun ≤ 20°) | bundle start |
| `/api/check` | every site: 60 d at start and 30 d at start + 60 d (landing ring); 30 d at start for the 3D ground view, panel heights 0, 1, 2, 5, 10 m at polar sites (2 m elsewhere) | bundle start |
| `GET /api/runs/{id}` | the runs behind those 30-day checks | – |
| `/api/compare` | every site, **one place at a time**, 30 days | start + 0, 7, 14, 21 d |
| `/api/landing-ellipse` | Sites 001 and 004, round, semi-axis 100 / 250 / 500 / 1000 m, 14 days | bundle start |

**Files:**
- `data/answers/index.json`: `{key_spec, baked_times, answers: {key: file}, runs: {run_id: file}, errors}`;
- each answer file is the unmodified response plus `"static_answer": true`.

### Frontend: one change in `post()` (src/api/plan.ts)

In static mode, route every POST through `src/data/staticAnswers.ts` (already written; it is the
mirror of `backend/lunar_core/static_answers.py` and is checked against shared vectors in
`tests/static_keys.golden.json`):

```ts
const ep = endpointOf(url, idx.key_spec);
if (!ep) throw new ApiError(404, 'needs the live server');
if (ep === 'compare') {
  // one stored answer per place: fetch each, concatenate rows, recompute leaders (rules below)
}
const file = idx.answers[makeKey(idx.key_spec, ep, body)];
if (!file) throw new ApiError(404, `Precomputed for ${idx.baked_times.join(', ')}; this question needs the live server.`);
return getJson(`${base}data/${file}`);
// GET /api/runs/{id}  ->  `${base}data/${idx.runs[id]}`
```

**Static-mode rules:**
- **Snap times:** snap the clock and every start or at time to `snapToBaked()`, and show
  "precomputed for 8 Jan 2027".
- **Landing search:** use the bundle start (`index.start_utc`).
- **Compare leaders** (same as `lunar_core.compare.leaders`):
  - highest wins for most sunlight, most Earth and most both;
  - lowest wins for shortest darkness;
  - longest until sunset / Earthset counts only places where the Sun / Earth is up now;
  - highest Sun now counts only places where the Sun is up;
  - ties are all listed.
- **Clicked points:** inside the 80 km polar square, answer from the forecast bits ("Sun x%,
  Earth y% this month, 240 m terrain, ground level"). Elsewhere, say "this needs the live server".

### Bake order (machine with kernels and DEMs)

```
.venv/bin/python tools/bake_static.py
.venv/bin/python tools/bake_answers.py        # ~45-60 min the first time; resumable
cd frontend/app && npm run build              # dist/ = the complete static site
```
