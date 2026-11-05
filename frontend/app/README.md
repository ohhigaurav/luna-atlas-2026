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
| `npm test` | unit tests: sky interpolation, formats, Moon phase, landing answer, typed dates, calendar days, site day/night, lander power model |
| `npm run check:shader` | the Moon shader in headless WebGL2: terminator within 1 deg of the Sun direction, map orientation, slope sign, cast shadows, no speckle from sub-pixel relief (10 criteria) |
| `npm run build` | TypeScript (strict) + production bundle in `dist/` |

## What is on screen

| piece | file | data |
|---|---|---|
| Globe: LROC colour, LOLA relief and cast shadows, Earth, Sun glare, opening shot, flights | `src/engine/` (plain three.js, mounted by `GlobeView.tsx`) | `POST /api/sky-geometry` |
| Site pins (buttons, clustered at the pole) | `src/engine/pins.ts` | `GET /api/reference-sites` |
| Site index (left): every site, day or night now and when that changes, flat ground | `src/ui/SiteIndex.tsx`, `src/state/siteState.ts` | sky-geometry vectors |
| Top bar: UTC clock (live dot while it follows the wall clock), "% lit from Earth" | `App.tsx`, `src/state/phase.ts` | sky-geometry vectors |
| Site panel (right): next landing date, daylight / Earth / countdown, fixes when nothing fits, mission length, launch date, quick dates, 90-day strip | `src/plan/SitePanel.tsx`, `src/plan/answer.ts` | `POST /api/landing-windows` + `POST /api/check` bands |
| Landing ring: 90 days around the pin, launch knob, mission-length handle | `src/plan/LandingRing.tsx` | same |
| Calendar heat map: each UTC day green (window), amber (Sun up), grey (dark) | `src/plan/Calendar.tsx`, `src/plan/calendarDays.ts` | same |
| Ctrl K: sites, typed dates (`13 jan 2027`, `next month`, `2027-03`, `+10d`), actions | `src/ui/CommandBar.tsx`, `src/state/when.ts` | none |
| Surface: the real horizon with the Sun and Earth now and over 30 days; "Keep the lander alive" battery game (illustrative power model, labelled) | `src/surface/` | `POST /api/check` → `GET /api/runs/{id}` series |
| Evidence: LRO photo vs our shadows wipe slider (6 frames, the failing one included), real-mission table, JPL Horizons | `src/proof/` | `public/proof/` (from `python tools/export_proof.py`), figures copied from `validation/evidence/` |
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
