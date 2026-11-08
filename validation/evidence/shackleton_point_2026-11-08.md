# The "Shackleton crater" reference point is on the inner wall; Earth grazes the opposite rim (2026-11-08)

**Found by:** reading the static bake (a development laptop, v0.7.45, Jan 2027, 30 days, 240 m regional map).
The point read **Sun 0%, Earth 15.6%** at every mast height (0, 1, 2, 5, 10 m). Earth visible from
inside a permanently shadowed crater looked like a possible bug, so we checked where the point is and
why. No pass rule: a diagnostic.

**Where the point is.** `reference-shackleton-crater` = 89.4°S, 129.4°E (a peer-reviewed study's
approximate position). The USGS/IAU Gazetteer gives Shackleton's centre as 89.67°S, 129.78°E, with
diameter 20.92 km (https://planetarynames.wr.usgs.gov/Feature/5450). The point is ~8.2 km from the
centre (0.27° of latitude at 30.3 km/deg), inside the ~10.5 km rim radius: on the far-side inner wall,
not on the floor. Its DEM ground height is −318 m (1737.4 km sphere).

**What the baked runs show** (identical for both bake passes; raw console output in the chat of 8 Nov):

| mast | lowest horizon | highest horizon | Earth clear | Earth max elevation | Sun's best margin |
|---|---|---|---|---|---|
| 0 m | 4.54° | 30.61° | 224 / 1442 samples (15.5%) | 6.07° | el −0.00° vs horizon 4.54° (az 219°) |
| 2 m | 4.53° | 30.54° | 224 / 1442 | 6.07° | −0.00° vs 4.53° |
| 10 m | 4.50° | 30.26° | 224 / 1442 | 6.07° | −0.00° vs 4.50° |

Earth, when clear, sits at azimuth 222.8–226.6°, exactly where the horizon is lowest (across the crater),
at 4.83–5.21° near the start and end of its visibility against a horizon of 4.80–5.22° there.
(Horizon values in this table come from a nearest-bin lookup in the check script; production interpolates
between 0.5° bins, so hundredths of a degree here are approximate.)

**Reading it:**
- **Physically consistent, not a bug.** At this latitude Earth climbs to ~6° and stays in one direction
  (librations move it a few degrees); the wall behind the point blocks everything except a ~4.5° notch
  over the opposite rim, and Earth's direction falls in that notch. The Sun never exceeds ~0° in this
  month, so it never clears 4.5°: 0% Sun is robust.
- **Marginal at the edges.** Earth's rise and set over the rim happen within hundredths of a degree of
  the horizon, measured on the 240 m map. 20 m of terrain error at the ~18 km opposite rim is ~0.06°,
  so the start and end of each Earth pass (and the 15.5%) carry real uncertainty. The middle of the pass
  (Earth ~1° above the notch) does not.
- **Label:** the point is a crater reference, not the crater floor. The floor itself was a separate
  point in the shadow match, where it reads dark as expected ("Shackleton floor −21.84° (dark)",
  `shadow_match_2026-11-04.md`).
