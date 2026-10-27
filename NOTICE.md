# Third-party notices and data provenance

This file is the source-of-truth register for third-party software, data, kernels, code, and visual assets used by the project. Add an entry before integrating an external asset.

| Asset / source | Version or product | Licence / terms | Used for | Retrieval date | SHA-256 / evidence |
|---|---|---|---|---|---|
| NASA Space Apps Challenge page | Lunar Landing Site Navigator, 2026 | NASA Space Apps terms | Problem statement and source citation | 2026-10-24 | URL recorded in README; archive/hash to add |
| NASA Space Apps participant terms | 2026 terms, updated 2026-08-07 | Participant terms | Eligibility and source attribution rules | 2026-10-24 | URL recorded in README; archive/hash to add |
| NASA NAIF CSPICE `azlcpo_c` documentation | `azlcpo_c`, Version 1.0.0 (2021-11-01) | NASA NAIF technical reference | `geometry.py` call signature, local topocentric coordinates and output units | 2026-10-25 | https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/azlcpo_c.html |
| SpiceyPy | 8.3.0 (dependency pin) | Upstream package licence applies; verify against package metadata when lock is generated | Python binding to CSPICE used by `geometry.py` | 2026-10-25 | https://pypi.org/project/spiceypy/ |

No NASA kernels, DEMs, competitor source code, or official candidate-site data are bundled in this prototype. Add each asset's exact URL, product/version, licence, retrieval timestamp, byte size, SHA-256, coordinate/frame conventions, and parser/transform history before use. The dependency lock remains to be generated with registry access.


## NASA data sources and attribution

- NASA Goddard Planetary Geology, Geophysics and Geochemistry Laboratory (PGDA), **High-Resolution LOLA Topography for Lunar South Pole Sites**, Product 78: https://pgda.gsfc.nasa.gov/products/78 . Product-specific files must retain their publisher URL, retrieval timestamp, byte count, SHA-256, product ID and the metadata review record.
- NASA Goddard PGDA, **A New View of the Lunar South Pole from LOLA**, Product 90: https://pgda.gsfc.nasa.gov/products/90 . Regional COG rasters are source data, not derived work; cite Barker et al. (2023), Planetary Science Journal 4, 183, https://doi.org/10.3847/PSJ/acf3e1 .
- NASA/JPL Navigation and Ancillary Information Facility (NAIF), SPICE generic kernels and frame documentation: https://naif.jpl.nasa.gov/ . Keep the selected kernel set's manifest and per-file hashes with every run.
- JPL Horizons: https://ssd-api.jpl.nasa.gov/doc/horizons.html . Any golden query must be archived with its raw response and exact query parameters.

Data downloads are not bundled in the source archive and are not represented as pre-validated. The application records file-level provenance locally.
