# Gate P: sunlight power on real data — PASS

Run 2026-11-13T10:06:32Z, commit 2e4135ac919f5145aa7fd1b0e59a138d54a7a671, server https://13-54-224-119.sslip.io (API 0.7.72.dev0). Rules `validation/power_tolerances.json` (sha256 4f97326f5e5503e5…, predeclared 2026-11-13T10:30:00Z, approved by the team, 2026-11-13T10:02:13Z, before the first Gate P run).

Not an independent validation. No published power or irradiance time series for these points is compared. The disc visibility it is built on passed Gate E (NASA Goddard PGDA 69 maps); this gate checks that the power layer is consistent with it and stays inside physical bounds on real data.

| Date (30 d) | Site | Terrain | Disc % | Mean vertical W/m² | Mean flat W/m² | kWh/m² | Partial Sun % | First sunrise → full disc | Checks |
|---|---|---|---|---|---|---|---|---|---|
| 2027-01-01 | reference-lola-site-001 | 5.0 m | 65.9 | 930 | 15.2 | 670 | 6 | 2027-01-27T12:09Z, sets first | P1:ok P3:ok P4:ok P6:ok |
| 2027-01-01 | reference-lola-site-004 | 5.0 m | 0.0 | 0 | 0.0 | 0 | 0 | — | P1:ok P5:ok |
| 2027-08-01 | reference-lola-site-001 | 5.0 m | 65.9 | 876 | 7.9 | 631 | 8 | 2027-08-21T15:20Z, 37.7 h | P1:ok P2:ok P3:ok P4:ok P6:ok |
| 2027-08-01 | reference-lola-site-004 | 5.0 m | 0.0 | 0 | 0.0 | 0 | 0 | — | P1:ok P5:ok |
| 2027-10-15 | reference-lola-site-001 | 5.0 m | 80.3 | 1108 | 31.4 | 797 | 3 | 2027-10-16T19:12Z, 15.8 h | P1:ok P2:ok P3:ok P4:ok P6:ok |
| 2027-10-15 | reference-lola-site-004 | 5.0 m | 0.0 | 0 | 0.0 | 0 | 0 | — | P1:ok P5:ok |

Details of every check are in the .json.

## Notes added after the run (13 Nov, backend session; they change no result)

- **Timestamp correction.** The rules file says `predeclared_utc: 2026-11-13T10:30:00Z`. That time was typed wrongly
  (a guess, later than the real time). The git record is authoritative: the rules were committed in `94b8823` at
  2026-11-13T09:59:47Z, approved in `2e4135a` at 10:02:13Z, and this run started at 10:06:32Z. The file is left
  unchanged so its sha256 above still matches.
- **Jan 2027 peak 1414.8 W/m², close to the 1416 bound.** It implies a Sun–Moon distance of 0.98081 AU: a new Moon
  near Earth's perihelion (0.98329 − 0.00248 AU). Physically expected and inside the derived range (≥ 0.98057 AU).
- **Jan and Aug Site 001 disc 65.9% both:** 65.943% vs 65.932%; the rows differ in every other field (coincidence).
- **What the numbers show** (Site 001, 2 m panel, 5 m terrain): the first sunrise takes 15.8 h (Oct) to 37.7 h (Aug)
  to clear the whole disc, and in Jan the Sun sets again with only 0.11% of the disc ever up. A flat panel gets
  0.9–2.8% of what a vertical Sun-facing panel gets. Time steps are 30 min, so sunrise durations are ±0.5 h.
