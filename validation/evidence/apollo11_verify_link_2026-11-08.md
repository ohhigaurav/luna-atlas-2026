# Apollo 11 "verify with NASA JPL" spot check, 2026-11-08

Run by the team at v0.7.45 (`4432f40`), local server. A spot check of the app's verify link, not a gate:
no pass rule was set, and the systematic comparison is Gate B (`gate_b_geometry_2026-10-28.md`,
worst 0.04″). Our value comes from `POST /api/check` (Apollo 11, `reference-apollo-11`,
0.67416°N 23.47314°E, flat horizon, observer 2 m) at 2027-01-13T17:00:00Z; JPL's from the
Horizons URL that the same answer carries (`coord@301`, airless apparent, UT).

| body | ours az / el (deg, as shown, 4 dp) | JPL Horizons az / el (deg) | difference |
|---|---|---|---|
| Sun | 90.8449 / 5.1466 | 90.844887444 / 5.146565009 | +0.0″ / +0.1″ |
| Earth | 260.9846 / 58.9364 | 260.984658599 / 58.936413736 | −0.2″ / −0.0″ |

Raw Horizons rows:

```
2027-Jan-13 17:00:00.000 *i   90.844887444   5.146565009  1.4696978840E+08   0.9180284
2027-Jan-13 17:00:00.000 *i  260.984658599  58.936413736  3.9157838243E+05  -0.0509917
```

Reading: the differences are the 4-decimal rounding of the displayed value (0.0001° = 0.36″)
plus at most Gate B's 0.04″. The verify link a judge clicks gives the same numbers as the app.
