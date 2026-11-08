# Luna Atlas app (frontend/app)

The Luna Atlas web app: a 3D Moon lit by the real Sun and Earth, where you pick a landing site and
see **when you can land there and whether the Sun and Earth stay up**. Every lit pixel and every
number comes from the FastAPI backend (JPL SPICE ephemerides, NASA LOLA terrain); the app draws and
labels, it never computes science or invents a number.

The spec is an internal document (not published) (read **Phase 2** first). The API
it uses is in [`docs/frontend_api.md`](../../docs/frontend_api.md).

## Run it

```bash
cd frontend/app && npm install            # once
npm run textures                          # once: NASA Moon/Earth maps (~270 MB; MOON_RES=lite for ~5 MB)
cd ../.. && ./scripts/run_local.sh        # builds this app if it changed, then serves it and the API
```

Open http://127.0.0.1:8000. The old four-screen app is frozen at `/legacy`.

While developing, keep the backend running and use Vite's dev server for instant reloads:

```bash
cd frontend/app && npm run dev            # http://localhost:5173, /api is proxied to :8000
```

## Checks

| command | what it checks |
|---|---|
| `npm test` | unit tests: sky interpolation, formats, Moon phase, landing answer, typed dates, calendar days, site day/night, lander power model, pin outlook, forecast mask indexing (against numpy) |
| `npm run check:shader` | the Moon shader in headless WebGL2: terminator within 1 deg of the Sun direction, map orientation, slope sign, cast shadows, no speckle from sub-pixel relief (10 criteria) |
| `npm run build` | TypeScript (strict) + production bundle in `dist/` |

## What is on screen

| piece | file | data |
|---|---|---|
| Globe: LROC colour, LOLA relief and cast shadows, Earth, Sun glare, opening shot, flights | `src/engine/` (plain three.js, mounted by `GlobeView.tsx`) | `POST /api/sky-geometry` |
| Site pins (buttons, clustered at the pole) | `src/engine/pins.ts` | `GET /api/reference-sites` |
| Date bar (top): the moment every answer is for; day steps, picker, play, Now, scrub | `src/ui/DateBar.tsx` | shared clock |
| Site card: origin tag (official / reference / your point), our measured note with evidence + "Try" point, plain verdict for the date, Sun and Earth now with sunset/Earthset, actions; Details = expert controls | `src/plan/SiteCard.tsx`, `src/plan/SitePanel.tsx` (details) | `/api/landing-windows`, `/api/compare` |
| Best date on the site card: 30/90/180/365-day look-ahead, soonest / most sunlight / most Earth contact; mission-length chips | `src/plan/BestDate.tsx`, `src/plan/SiteCard.tsx` | `/api/landing-windows` (`soonest`, `best`, `best_earth`) |
| Pin key: tap a line to list its sites and why | `src/ui/PinKey.tsx`, `src/state/outlook.ts`, `src/state/rules.ts` | `/api/landing-windows` |
| Static site answers (no backend): POSTs and runs from the baked `data/answers/` | `src/data/staticMode.ts`, `src/data/staticAnswers.ts` | `tools/bake_answers.py` output |
| Home: welcome and pin legend with counts | `App.tsx`, `src/state/outlook.ts`, `src/state/siteState.ts` | `/api/landing-windows` (all sites, cached), sky-geometry |
| Green pins: a landing window within 30 days; amber: Sun up now; hollow: night | `src/engine/pins.ts`, `src/plan/useOutlook.ts` | same |
| Marginalia: UTC clock (live dot while it follows the wall clock), "% lit from Earth", grid | `App.tsx`, `src/state/phase.ts` | sky-geometry vectors |
| Site view (in the title block): next landing date, daylight / Earth / countdown, fixes when nothing fits, mission length, launch date, quick dates, 90-day strip | `src/plan/SitePanel.tsx`, `src/plan/answer.ts` | `POST /api/landing-windows` + `POST /api/check` bands |
| Landing ring: 90 days around the pin, launch knob, mission-length handle | `src/plan/LandingRing.tsx` | same |
| Calendar heat map: each UTC day green (window), amber (Sun up), grey (dark) | `src/plan/Calendar.tsx`, `src/plan/calendarDays.ts` | same |
| Ctrl K: sites, typed dates (`13 jan 2027`, `next month`, `2027-03`, `+10d`), actions | `src/ui/CommandBar.tsx`, `src/state/when.ts` | none |
| Stand here in 3D: first-person view, the run's real horizon as the skyline, Sun and a Sun-lit Earth on the shared clock, ridge shadows, compass, battery card (illustrative power model, labelled) | `src/surface/Ground3D.ts`, `Surface3D.tsx`, `run.ts`, `power.ts` | `POST /api/check` → `GET /api/runs/{id}` |
| Evidence: LRO photo vs our shadows wipe slider (6 frames, the failing one included), real-mission table, JPL Horizons | `src/proof/` | `public/proof/` (from `python tools/export_proof.py`), figures copied from `validation/evidence/` |
| Moon weather forecast (F29): the south pole's sunlight every 2 h and Earth's line of sight every 6 h for January 2027, draped on the 3D pole in sync with the clock; layers (Earth, lit and Earth), probe point with month ribbon, hover readout | `src/forecast/`, `fc*` uniforms in `src/scene/lunarMaterial.ts` | `public/data/shadow_movie/` (`lit.u8`, `earth.u8`, `movie.json`, `earth.json`) from `tools/bake_shadow_movie.py`, `tools/bake_earth_movie.py` |
| Click anywhere: landing windows for any point (240 m terrain near the pole, flat elsewhere, labelled) | `App.tsx` (`pointId`), `src/api/plan.ts` | `/api/landing-windows`, `/api/check` with `latitude_deg`, `longitude_deg` |
| "Verify with NASA JPL ↗": our Sun/Earth position at best touchdown next to JPL Horizons' table for it | `src/plan/SitePanel.tsx` | `verify` on each opportunity |
| Compare: date from the bar, tap pins to add, big cards with plain badges; "All numbers" table with mini horizons | `src/compare/` (`CompareShelf`, `CompareView`, `useCompare`), `src/api/compare.ts` | `POST /api/compare` |
| Landing ellipse (polar sites): ~45 analyses inside the ellipse, best/worst, dark-trap share | `src/plan/EllipsePanel.tsx` | `POST /api/landing-ellipse` |
| Time rail, pointer readout (lat/lon and Sun height under the cursor) | `App.tsx` | shared clock |

**Live or static.** If the backend answers `GET /api/reference-sites`, the app is live ("the Moon
right now", any date). Otherwise it loads the precomputed judge bundle from `public/data/`
([`docs/static_bundle.md`](../../docs/static_bundle.md)) and disables what that cannot answer.

## Rules we keep

- No fake numbers. If the API cannot answer, the screen says so; it never fills in.
- Honesty labels stay visible: reference vs official site, real terrain vs flat horizon,
  "Earth in view" is geometry, not a radio link, Earth's rotation is not modelled, the star field is
  illustrative.
- Colour never carries meaning alone (glyphs ✓ ✕ and words go with it); keyboard reaches everything.
- Camera motion is presentation; the Sun, Earth and terminator move only with data.

## Evidence pictures (F22)

The wipe slider needs the shadow-match pictures, which are made on the machine that ran
`tools/shadow_match.py`. Copy them into the app once and commit them:

```bash
python tools/export_proof.py      # writes frontend/app/public/proof/
```

Without them the evidence screen still shows the verdict and every number (they come from the
committed evidence files) and says how to add the pictures.

## Textures

`npm run textures` (`scripts/fetch_textures.sh`) downloads NASA SVS CGI Moon Kit maps and the Blue
Marble into `~/.cache/luna-atlas`, resumes cut-off downloads, converts them (8k/4k colour JPEG,
16 px/deg LOLA heights with mipmaps and polar caps), and writes `public/textures/textures.json`,
which tells the app what exists. First runs pin SHA-256s in `scripts/sources.sha256` and
`scripts/textures.sha256`; commit those. Credit: NASA's Scientific Visualization Studio; NASA Earth
Observatory (Blue Marble).
