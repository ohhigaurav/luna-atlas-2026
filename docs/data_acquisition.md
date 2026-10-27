# Public Data Acquisition and Onboarding

**Build:** 0.7.0-dev  
**Purpose:** Acquire a reproducible public-reference stack before the official challenge catalogue is available.

## One command

```bash
./scripts/bootstrap_public_reference.sh
```

Optional modes:

```bash
./scripts/bootstrap_public_reference.sh --kernels-only
./scripts/bootstrap_public_reference.sh --skip-regional-dem
./scripts/bootstrap_public_reference.sh --skip-kernels --skip-regional-dem
./scripts/bootstrap_public_reference.sh --force
```

The normal run downloads:

| Asset | Publisher | Nominal resolution / span | Assignment |
|---|---|---|---|
| `naif0012.tls`, `pck00011.tpc`, lunar FK files, `de421.bsp`, `moon_pa_de421_1900-2050.bpc` | NAIF | Time conversion, body constants, frame chain, planetary ephemerides and lunar orientation | Shared geometry kernel pool, subject to frame/coverage preflight |
| `Site01_final_adj_5mpp_surf.tif` | NASA PGDA Product 78 | 5 m/pixel near-field surface DEM | `reference-lola-site-001`; 0–8 km range contract |
| `Site04_final_adj_5mpp_surf.tif` | NASA PGDA Product 78 | 5 m/pixel near-field surface DEM | `reference-lola-site-004`; 0–8 km range contract |
| `LDEM_60S_240MPP_ADJ.TIF` | NASA PGDA Product 90 | 240 m/pixel regional surface DEM covering 60°S–90°S; roughly 210 MB published file size | Shared regional fallback; 0–200 km, overridden by 5 m tiles where those cover the site |

Official source pages:

- Product 78: https://pgda.gsfc.nasa.gov/products/78
- Product 90: https://pgda.gsfc.nasa.gov/products/90
- Product 104: https://pgda.gsfc.nasa.gov/products/104 (supplemental 5 m SDEM for earlier Artemis III candidate regions; not automatically registered or treated as the official 2026 site catalogue)
- NAIF generic kernel tree: https://naif.jpl.nasa.gov/pub/naif/generic_kernels/
- JPL Horizons API: https://ssd-api.jpl.nasa.gov/doc/horizons.html

## Integrity contract

The bootstrap script only accepts HTTPS URLs from exact allowlisted publisher hosts, validates redirect destinations, caps each download size, streams to an atomic temporary file, compares advertised and actual byte counts when available, and computes SHA-256. It inspects the raster CRS/transform/scale/offset/NoData metadata and confirms that the chosen literature reference point lands inside a non-NoData pixel.

For each DEM asset, the manifest captures `source_url`, `product_id`, `retrieved_utc`, `size_bytes`, `sha256`, native pixel spacing, declared units, range assignment, CRS/frame description and a raster metadata snapshot. Existing bytes are reused only if the manifest already attests to the same URL, size and digest. Use `--force` to intentionally refresh.

## What the bootstrap does not certify

The script does not infer that a working CRS transformation proves the correct lunar frame/radius, nor that a publisher's phrase “surface height” proves compatibility with the observer's radius convention. It deliberately leaves both `crs_contract_verified` and `vertical_datum_verified` false. A reviewer must examine the actual GeoTIFF metadata, known point coordinates, axis convention, height units, lunar body radius and the observer-point equation, then record a specific, reproducible verification note. No code path should silently flip those flags.

The regional dataset spans 60–90° S, not the whole Moon; this latitude extent is necessary to cover a 200 km horizon range at candidate locations nearer the poleward edge of the 80°S parallel. The two 5 m rasters are local area products and are assigned to their corresponding literature reference points (`reference-lola-site-001` and `reference-lola-site-004`). Product 90 is registered as a shared regional fallback. At Site01/Site04 the finer Product 78 asset wins for ranges it covers; elsewhere the regional raster may be the only available elevation source. All reference points are checked against the actual raster bounds and NoData before registration. The resolution of 240 m/pixel does not imply 240 m vertical accuracy; the regional layer is a lower-resolution far-field model, not a replacement for near-site terrain detail. These files are not automatically assigned to the official challenge-site catalogue. If an official point is outside raster coverage, the importer must fail or the horizon coverage must be marked incomplete.

## After official challenge datasets are released

1. Download the unmodified official data file to `data/raw/` and record publisher URL, retrieval UTC, file bytes and SHA-256.
2. Import only verified point records using `tools/import_official_sites.py`. Preserve original IDs, coordinate semantics, longitude direction and source rows.
3. For each official site, inspect whether a matching Product 78 tile actually exists. If so, register it with its true site ID; otherwise do not claim terrain-aware results for that point.
4. Run coordinate round-trips and an independent review before enabling the DEM flags.
5. Run SPICE at at least three predeclared epochs for two or more sites (including near horizon), store JPL Horizons query/response files, and use the tolerance file approved before observing errors.
6. Compare real terrain outputs against synthetic horizon cases, inspect incomplete bins, and document any coverage gaps before publishing.

## Offline behavior

The bootstrap requires network access. After data retrieval and a reviewed run have been completed, keep raw data files in local ignored asset directories and save the analysis JSON/CSV under `data/runs/`. The app can load saved output offline; it does not re-compute SPICE or terrain in the browser.
