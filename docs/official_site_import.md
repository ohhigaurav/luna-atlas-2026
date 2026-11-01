# Importing the official site list (13 Nov 2026)

The Resources tab of "10 – CLPS Lunar Landing Site Navigator" is scheduled for 13 Nov 2026 (D-02).
Its site-list format is unknown. This is the procedure for getting it into
`data/catalogue/sites.json` without guessing.

## 1. Archive what was published

Save every resource file unmodified, plus a PDF/HTML capture of the Resources tab, and record
SHA-256 and retrieval time (UTC). Do not edit these files.

## 2. Dry run

```bash
python3 tools/import_official_sites.py <file> \
  --source-url "https://www.spaceappschallenge.org/2026/challenges/..." --dry-run
```

Accepted: `.csv/.tsv/.txt` (comma, semicolon, tab or pipe), `.xlsx` (`--sheet NAME` if several),
`.json` (array of records, or an object holding exactly one array), `.geojson` (Point features,
`[lon, lat]`), `.kml` (Placemark Points). PDF tables are refused: transcribe to CSV, keep the PDF
next to it, and have a second person check every coordinate against the PDF.

The dry run prints, for every row, the raw latitude/longitude text, the parsed values and **how
the longitude sign convention was established**. Read every line.

## 3. Resolve what the importer refuses

| Message | Meaning | Fix |
|---|---|---|
| `no stated sign convention` | plain longitude numbers, no E/W letter, no convention column or header | find the convention in the resource documentation, then `--longitude-direction east_positive` (or `west_positive`) |
| `latitude type not stated` | no latitude-type column | `--latitude-type planetocentric` if the documentation says so; on the IAU spherical Moon used here both types are numerically equal |
| `several columns could be the latitude` | ambiguous headers | `--column latitude="Exact Header"` (roles: id, name, latitude, longitude, latitude_type, longitude_direction) |
| `conflicting longitude conventions` / `contradicts header` | the file disagrees with itself or with your flag | stop and read the source; do not override |
| `minus sign and a hemisphere letter` | e.g. `-10 W` | ambiguous in the source; ask the organisers or record the interpretation in the decision log |
| `comma decimal separator` | e.g. `89,5` | convert explicitly and record that you did |

Never edit the official file to make it import. If a transcription or conversion is unavoidable,
keep it as a separate file and record it in the decision log.

## 4. Import

Run the same command without `--dry-run`. This writes:

* `data/catalogue/sites.json`: the validated catalogue (written only if every row passes);
* `data/catalogue/sites.source_rows.json`: every raw row, the column map, the warnings;
* `data/catalogue/sources/<sha16>_<file>`: a byte-identical copy of the source file.

Duplicate coordinates under different names are reported as warnings. Review them.

## 5. After import

* Compare the official list with `data/reference/landing_sites_standin.csv`. Where the same
  mission appears in both, the difference in coordinates is a useful sanity check (expect metres to
  hundreds of metres, not degrees).
* Check which official sites fall outside registered DEM coverage (D-22). Those get no terrain
  horizon until coverage exists.

## Stand-in list until then

`data/reference/landing_sites_standin.csv` holds 18 published landing sites (Apollo LMs, flown
CLPS landers, two future CLPS target regions, Chang'e 3–6, Chandrayaan-3, SLIM, Luna 24), one
cited source per row, written in each source's own notation. `tools/build_reference_sites.py`
runs it through the same parser and merges it into `data/reference/reference_sites.json`
(`kind: mission_landing_site`). `--check` verifies the JSON is current. These are reference
sites only; the official catalogue stays empty until step 4.
