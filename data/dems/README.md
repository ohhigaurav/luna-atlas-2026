# DEM asset intake

Large raster assets are intentionally not stored in Git. Place downloaded rasters outside the repository, inspect them with `gdalinfo`/Rasterio, then register a copy into `data/dems/assets/` using `tools/register_dem.py`.

The tool records the asset URL, product ID, content SHA-256, raster CRS, transform, dimensions, NoData, dtype and block layout. It defaults both `crs_contract_verified` and `vertical_datum_verified` to false. Terrain analysis refuses to run until an analyst records a concrete verification note for each. This matters because a file's projection and nominal pixel spacing do not by themselves prove that its Z values are compatible with the lunar reference radius/observer-height convention.

PGDA Product 78 is designed for high-resolution south-pole terrain, with 5 m/pixel DEMs and 100 alternative realizations. Product 90 supports regional far-field coverage. Use native raster data for quantitative reads, not COG overview levels. Product 69 is a long-term illumination product for broad sanity checking only.

The first end-to-end pipeline must include a projection round-trip test, coverage map and a second-person review of one actual horizon. Until then, set neither verification boolean true for real data.
