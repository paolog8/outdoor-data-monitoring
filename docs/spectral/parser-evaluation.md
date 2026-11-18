# Evaluation of Marko's spectral parser

Run of `001_v1_Parse_spectral_data.ipynb` against the spectral files available in
`data/spectral_data/`, and a comparison with the parser in `ingestion/spectral.py`.
The goal was to see whether the notebook's output matches what we already parse and
whether it holds up against the files we actually have.

## Files used

| File | Header rows | Sensors per timestamp | Instrument |
|---|---|---|---|
| `2026/2026020112.CSV` | 7 (no `Wavelength(nm)` row) | MS-711, MS-712 | `EKO WISER 35` |
| `2018/2018080712.CSV` | 8 (with `Wavelength(nm)` row) | MS-711, MS-712, Merge | `EKO WISER` |

Both files cover 300–1800 nm at 1 nm steps and contain 8 or 12 consecutive
5-minute measurements. Only these two files are available locally; the network share
was not reachable.

## How it was run

The notebook reads the Windows share `\\basisit.de\...` directly, so its two folder
patterns were pointed at the local copies. Everything else — `parse_file`, the DuckDB
schema, the insert loop and the `sensor_info` seed — ran unchanged. Dependencies were
`duckdb`, `pandas` and `numpy` in a throw-away virtualenv.

## Results

- Both files parse. 24 points per file: 8 × 3 sensors for 2018, 12 × 2 for 2026.
- Processing time: 27 ms per file locally (Marko measured 133 ms per file over the
  share for the 2025+2026 folders).
- `spectral.irradiance` and `spectral.ape` stay `NULL` for every row: the table has
  columns that the insert (`df.filter(['timestamp', 'spectra', 'sensor'])`) never fills.
- `Exposure Time(msec)`, `Sensor Temp.(deg)` and `Power(V)` are parsed per point but
  not stored anywhere; only `spectra` and `sensor` survive into the database.
- Timestamps are naive local time. The notebook does no time-zone handling, and DuckDB
  `TIMESTAMP` carries none either.
- Re-running the notebook starts with `drop_create_db`, so it reloads every file from
  scratch: no ingestion log, no idempotent upsert, no record of what was already parsed.

### Defect: the 2025/2026 layout loses the 300 nm row

`parse_file` assumes 8 header rows unconditionally:

```python
meta_data = file[:7]
spectral_data = file[8:]
```

The 2025+ files (the ones the notebook is pointed at) have only 7 header rows, so
`file[8:]` silently drops the first data row, the 300 nm one. The parsed wavelengths
then run from **301** to 1800 nm and every spectrum is shifted by one nanometre
relative to the wavelength axis seeded in `sensor_info` (300–1799 nm):

```
file 300.00 nm row : 0.37, 0.47, 0.62
parsed spectra[0:3]: 0.47, 0.62, 0.76      # values of 301, 302, 303 nm
```

The 2018 file has the label row at line 8, so it parses correctly and its wavelengths
come out as 300–1800 nm. The same code is therefore right for old files and wrong for
new ones, without any warning.

A second axis inconsistency comes from `sensor_info`: it is seeded with
`np.arange(300, 1800)` — 1500 entries ending at 1799 — while the 2018 file has 1501
wavelengths and the 2026 file has 1500 starting at 301. No combination lines up with
the stored spectra for both file generations.

### Missing validation

There is no check of the header labels, the column count or the wavelength axis.
`parse_file` builds one record per header column and indexes the data array with
`spectral_data[idx + 1]`, so a file with an extra or missing column either raises deep
inside `numpy` or produces records paired with the wrong spectra. Errors are caught in
the caller and printed, then the file is skipped; nothing records that it was skipped.

### What the 2018 output shows about `Merge`

The 2018 file has a third column per timestamp named `Merge`. It is not a copy of
either head: up to 1117 nm it follows MS-711, from 882 nm it follows MS-712, and in the
882–1117 nm overlap it is close to but not equal to MS-711 (e.g. 645.33 vs 607.65 from
MS-712, stored 644.58). It looks like an instrument-side merged spectrum with its own
correction, not a plain sum or selection. Files from 2025 onward carry only the two
head columns, so a combined spectrum has to be derived at query time — and summing the
two heads, as `docs/ingestion-patterns.md` currently suggests, would roughly double the
irradiance in the overlap region.

## Comparison with `ingestion/spectral.py`

For the 2018 file the two implementations agree exactly: all 24 points, all
irradiance values and all NaN positions are identical, and the repository parser also
keeps exposure time, sensor temperature and power per measurement, which the notebook
discards.

Timestamps are the other visible difference. The notebook keeps the naive local
values. `ingestion/spectral.py` attaches `tzinfo=UTC` to the same values instead of
converting from `Europe/Berlin` like the MPP, temperature and irradiance parsers do, so
the two parsers disagree by the DST offset. Nothing in the CSV states whether the WISER
clock runs on local or UTC time, and the diurnal shape of the two files available does
not settle it (both hours were partly cloudy). This needs to be settled before
historical spectra are aligned with other measurements.

For the 2026 file the comparison cannot be made: `ingestion/spectral.py` rejects the
file with

```
SpectralFileStructureError: row 7 col 0 is '300.00', expected 'Wavelength(nm)'
```

`validate_spectral_structure` requires the `Wavelength(nm)` label row that the newer
exports do not write. Any 2025+ spectral file is therefore refused by ingestion as a
structure mismatch, while Marko's notebook accepts it and mis-parses it by one
nanometre. Neither parser handles both layouts correctly today.

## Conclusions

- Marko's notebook is a good description of the file layout and of the fill-forward
  approach for the interleaved header columns; both are already in
  `ingestion/spectral.py`.
- Its output for the 2018 layout matches ours exactly, so nothing in the old files is
  being missed.
- The notebook is not a drop-in parser: it drops the 300 nm row on new files, keeps no
  wavelength-per-file information, discards measurement metadata, does no validation
  and no time-zone conversion, and reloads everything on every run.
- The repository parser has the mirror-image problem: it validates strictly but only
  knows the 2018 layout.
- `Merge` should stay a separate sensor (as decided for the ingestion), and the "sum
  both heads" recipe in the docs should not be used for a combined spectrum.
