# Lunar South Pole Mission Planner — Validation Report

- Report ID: `LSPMP-VAL-001`
- Software commit:
- Python / dependency lock hash:
- Report author / reviewer:
- Date UTC:
- Overall status: `NOT RUN` / `PASS` / `BLOCKED` / `FAIL`

## 1. Purpose and scope

State exactly which code revision, site IDs, date range, kernel set, DEM assets, settings and outputs are covered. This report covers only the checks executed below; it is not a landing-safety, flight-software, RF-link or power-system certification.

## 2. Immutable inputs

| Input | Source URL / product | Retrieved UTC | SHA-256 | Frame/CRS | Units / datum | Notes |
|---|---|---|---|---|---|---|
| Official site data | | | | | | |
| LSK | | | | | | |
| SPK | | | | | | |
| PCK/BPC/FK | | | | | | |
| DEM asset(s) | | | | | | |
| JPL Horizons query | | | | | | |
| JPL Horizons raw response | | | | | | |

## 3. Results ledger

Declare each tolerance before executing its comparison. Preserve failed outputs; never tune tolerance after inspecting an error.

| Gate / requirement | Test and predeclared tolerance | Observed result | Status | Evidence path + SHA-256 | Reviewer |
|---|---|---|---|---|---|
| AC-1 geometry vs Horizons | | | NOT RUN | | |
| AC-2 flat sphere analytic dip `< 1e-6 rad` | | | NOT RUN | | |
| AC-3 event-step convergence | | | NOT RUN | | |
| AC-4 metrics from exported windows | | | NOT RUN | | |
| AC-5 analysis performance | | | NOT RUN | | |
| AC-6 finder performance | | | NOT RUN | | |
| AC-7 six usability tasks | | | NOT RUN | | |
| AC-8 clean install + offline run | | | NOT RUN | | |
| Horizon synthetic cases | | | NOT RUN | | |
| Real DEM CRS/datum review | | | NOT RUN | | |

## 4. Methods

Describe query configuration, epochs, aberration correction, observer height/latitude type, frame chain, numerical solver, sampling policy, DEM ray step, NoData treatment, and hardware/runtime. Include commands and logs so another engineer can reproduce the result.

## 5. Uncertainty and limitations

Separate numerical error from model/data uncertainty. Discuss DEM interpolated-cell fraction, vertical-datum uncertainty, azimuth/range sampling sensitivity, local-extremum event completeness, frame/kernel limitations and any sites or epochs excluded from the gate.

## 6. Deviations and failures

List each deviation, effect on conclusions, owner, mitigation and retest. Do not bury failures in appendices.

## 7. Conclusion

Use “passed for the tested scope” rather than “validated” unless the complete required gates and independent review are complete. Cite exact evidence records and state what the tool does not establish.
