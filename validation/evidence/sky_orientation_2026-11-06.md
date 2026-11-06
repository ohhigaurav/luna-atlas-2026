# Sky orientation check (star rotation, Earth's face), 2026-11-06

The team ran `tools/check_sky_orientation.py` at `bebf8ec`. Limits were fixed in the tool before the
run. Real kernels; 2027 at a 6 h step (1,457 samples); 13 test epochs, every 30 days.

## Result as pre-registered: FAIL (A3)

| part | result | limit | verdict |
|---|---|---|---|
| A1 matrices orthonormal | max error 1.5e-9 | ≤ 1e-8 | PASS |
| A2 M @ J2000 Sun/Earth vectors vs MOON_ME vectors | max 3.5e-6° | ≤ 1e-4° | PASS |
| A3 Moon pole in J2000 | RA 272.458–273.408°, Dec 67.364–67.791° | within 1° of 270.0 / 66.5 | **FAIL** |
| A4 spin rate | 13.17634°/day | 13.17636 ± 0.5% | PASS |
| B Earth sub-Moon point vs JPL Horizons | all 13 within limits | 0.1° lon (×cos lat), 0.1° lat | PASS |

## Why A3 failed: the limit was wrong, not the frame

The limit assumed the IAU pole's periodic terms were "well under 1°". The 18.6-year term (E1) is
3.88° in RA and 1.54° in Dec. In 2027 that term puts the pole about 2.4–3.2° from RA 270° and
about 0.9–1.3° from Dec 66.5°.

**Post hoc check, not a gate:** the full IAU 2015 formula over the same samples gives RA
272.459–273.409°, Dec 67.364–67.791°. That matches our range to 0.001° at both ends. The formula
was evaluated after seeing the result.

The tool now uses the full formula (A3 v2, ≤ 0.05° from IAU 2015 on the sky). That limit was set
after this run, so a future v2 PASS is a consistency check only. **This run's verdict stays
FAIL.**

## B: Earth's sub-Moon point vs Horizons

PASS at all 13 epochs.
- **Latitude:** |Δ| ≤ 0.0016°.
- **Longitude:** the gap is **systematic at +0.078 to +0.092°** (×cos lat), always the same sign,
  with no trend over the year.
- **Likely cause, not isolated:** our Earth orientation comes from the generic PCK's low-precision
  IAU_EARTH model. Horizons uses the high-precision Earth rotation model.
- **Size:** 0.085° is about 9 km on Earth's surface, invisible on a drawn Earth (Earth's disc is
  about 2° across in the lunar sky).
- **Margin:** the offset is close to the 0.1° limit. A high-precision Earth PCK would remove it,
  but drawing Earth's face does not need that.

## Allowed claims

- Earth's face in the app: "matches JPL Horizons' sub-Moon point within 0.1° (13 dates in 2027)".
- Star sky: rotation exact to SPICE (3.5e-6°); the Moon's pole matches IAU 2015, shown after the
  fact; spin rate within 0.0002%.
- Not allowed: "orientation gate passed". It failed on a wrong limit, and that failure is part of
  the record.

## Custom point smoke test (same session, `tools/try_landing.py --point -89.45 223.2 --days 30`)

The forecast's brightest pixel ran through the custom-point path in 4.9 s, with terrain.
- **Opportunities:** touchdown 2027-01-09 21:00 – 01-23 21:00 UTC.
- **Best touchdown:** 01-09 21:00, Sun 1.1°. Sunlight lasts at least 32.1 days; that is a lower
  bound, because the window is still open at the end of the search.
- **Earth:** in view 100% of the mission.
- **Earth rule:** fails for 768 of 1,441 candidate times.
- **Caveats shown:** both 240 m regional-terrain caveats.
- **Verify link:** ours Sun az 291.7946°, el 1.0719° at 2027-01-09 21:00. The Horizons value is
  still to be read by opening the link (the sandbox cannot reach JPL).
