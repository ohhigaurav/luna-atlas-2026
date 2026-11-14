# Third-party notices and data provenance

This file is the source-of-truth register for third-party software, data, kernels, code, and visual assets used by the project. Add an entry before integrating an external asset.

| Asset / source | Version or product | Licence / terms | Used for | Retrieval date | SHA-256 / evidence |
|---|---|---|---|---|---|
| NASA Space Apps Challenge page | Lunar Landing Site Navigator, 2026 | NASA Space Apps terms | Problem statement and source citation | 2026-10-24 | URL recorded in README; archive/hash to add |
| NASA Space Apps participant terms | 2026 terms, updated 2026-08-07 | Participant terms | Eligibility and source attribution rules | 2026-10-24 | URL recorded in README; archive/hash to add |
| NASA NAIF CSPICE `azlcpo_c` documentation | `azlcpo_c`, Version 1.0.0 (2021-11-01) | NASA NAIF technical reference | `geometry.py` call signature, local topocentric coordinates and output units | 2026-10-25 | https://naif.jpl.nasa.gov/pub/naif/toolkit_docs/C/cspice/azlcpo_c.html |
| SpiceyPy | 8.3.0 (dependency pin) | Upstream package licence applies; verify against package metadata when lock is generated | Python binding to CSPICE used by `geometry.py` | 2026-10-25 | https://pypi.org/project/spiceypy/ |

The repository does not bundle NASA kernels or terrain files: the server downloads them from the NASA addresses below, and each run records the files it used.

## Licences of third-party software, fonts and images (Space Apps terms: "Use of third-party materials")

Luna Atlas's own code and text are MIT-licensed (`LICENSE`). Everything else it uses is open source or public NASA material:

| Material | Licence | Used for |
|---|---|---|
| SpiceyPy (wraps NASA NAIF CSPICE) | MIT; CSPICE is NASA/JPL NAIF software, freely available | Sun and Earth geometry |
| FastAPI, Starlette | MIT, BSD-3-Clause | Web API |
| NumPy, SciPy | BSD-3-Clause | Numerics |
| rasterio, GDAL | BSD-3-Clause, MIT | Reading terrain rasters |
| pyproj | MIT | Map projections |
| Pydantic, Uvicorn | MIT, BSD-3-Clause | API models, web server |
| Pillow (demo-video tool only) | MIT-CMU | Captions in the demo video |
| React, React DOM | MIT | Web interface |
| three.js, React Three Fiber, drei | MIT | 3D Moon |
| Vite | MIT | Front-end build |
| Instrument Sans font | SIL Open Font License 1.1 (`frontend/app/src/assets/fonts/OFL-Instrument-Sans.txt`) | Interface font |
| Docker, Caddy | Apache 2.0 | Running and serving the app |
| NASA SVS CGI Moon Kit, NASA Blue Marble | NASA imagery, free to use with credit | Moon and Earth textures (display only) |
| NASA LOLA terrain (PGDA), NAIF kernels, LRO camera images (NASA/GSFC/Arizona State University) | NASA data, free to use with credit | Computation and validation |

AI tools: Claude (Anthropic) assisted with code and documentation; the project logo was generated with ChatGPT (OpenAI) image generation and carries a visible "AI-generated" mark, as the Space Apps rules require.


## NASA data sources and attribution

- NASA Goddard Planetary Geology, Geophysics and Geochemistry Laboratory (PGDA), **High-Resolution LOLA Topography for Lunar South Pole Sites**, Product 78: https://pgda.gsfc.nasa.gov/products/78 . Product-specific files must retain their publisher URL, retrieval timestamp, byte count, SHA-256, product ID and the metadata review record.
- NASA Goddard PGDA, **A New View of the Lunar South Pole from LOLA**, Product 90: https://pgda.gsfc.nasa.gov/products/90 . Regional COG rasters are source data, not derived work; cite Barker et al. (2023), Planetary Science Journal 4, 183, https://doi.org/10.3847/PSJ/acf3e1 .
- NASA/JPL Navigation and Ancillary Information Facility (NAIF), SPICE generic kernels and frame documentation: https://naif.jpl.nasa.gov/ . Keep the selected kernel set's manifest and per-file hashes with every run.
- JPL Horizons: https://ssd-api.jpl.nasa.gov/doc/horizons.html . Any golden query must be archived with its raw response and exact query parameters.

Data downloads are not bundled in the source archive and are not represented as pre-validated. The application records file-level provenance locally.
