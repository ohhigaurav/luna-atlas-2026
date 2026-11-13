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
