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
| `npm test` | unit tests: sky interpolation, display formats, Moon phase, landing answer logic |
| `npm run check:shader` | the Moon shader in headless WebGL2: terminator within 1 deg of the Sun direction, map orientation, slope sign, cast shadows (9 criteria) |
| `npm run build` | TypeScript (strict) + production bundle in `dist/` |

## What is on screen

| piece | file | data |
|---|---|---|
| Globe: LROC colour, LOLA relief and cast shadows, Earth, Sun glare, opening shot, flights | `src/engine/` (plain three.js, mounted by `GlobeView.tsx`) | `POST /api/sky-geometry` |
| Site pins (buttons, clustered at the pole) | `src/engine/pins.ts` | `GET /api/reference-sites` |
| Live clock and "% lit from Earth" chip | `App.tsx`, `src/state/phase.ts` | sky-geometry vectors |
| Answer card: next landing date, ☀ / 🌍 / ⏱ chips, fixes when nothing fits | `src/plan/AnswerCard.tsx`, `src/plan/answer.ts` | `POST /api/landing-windows` |
| Landing ring: 90 days around the pin, launch knob, mission-length handle | `src/plan/LandingRing.tsx` | landing windows + `POST /api/check` bands |
| Time dock | `App.tsx` | shared clock |

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

## Textures

`npm run textures` (`scripts/fetch_textures.sh`) downloads NASA SVS CGI Moon Kit maps and the Blue
Marble into `~/.cache/luna-atlas`, resumes cut-off downloads, converts them (8k/4k colour JPEG,
16 px/deg LOLA heights with mipmaps and polar caps), and writes `public/textures/textures.json`,
which tells the app what exists. First runs pin SHA-256s in `scripts/sources.sha256` and
`scripts/textures.sha256`; commit those. Credit: NASA's Scientific Visualization Studio; NASA Earth
Observatory (Blue Marble).
