# Spectral data: reference notebook and evaluation

`001_v1_Parse_spectral_data.ipynb` is Marko's notebook for parsing the EKO WISER
spectral CSVs from the outdoor measurement PC. It was received on 2026-11-18 and is
kept here unchanged, as delivered, so the original approach stays available next to the
production parser in `ingestion/spectral.py`.

## What the notebook does

- `parse_file(path)` reads one WISER CSV: the first seven rows are header metadata
  (`Date`, `Time`, `Memo`, `Sensor`, `Exposure Time(msec)`, `Sensor Temp.(deg)`,
  `Power(V)`), row 8 onward is the wavelength table (`np.genfromtxt`). Missing header
  cells are filled forward from the previous column, which is what the interleaved
  two-sensor layout requires.
- `drop_create_db(con)` / `insert_into_db(con, data)` write the parsed points into a
  DuckDB database with two tables:

  ```sql
  sensor_info(sensor VARCHAR, wavelenghts DOUBLE[])
  spectral(timestamp TIMESTAMP, sensor VARCHAR, ape DOUBLE, irradiance DOUBLE, spectra DOUBLE[])
  ```

- The remaining cells glob the network share
  `\\basisit.de\share\Outdoor-Data\ZPV\spectral\WISER_35\WSDac\{2025,2026}\*.csv`,
  parse every file, insert it, and print the mean processing time (about 133 ms per
  file over the 2025+2026 folders). The last cell seeds `sensor_info` with a
  300–1800 nm axis for `MS-711`, `MS-712` and `Merge`.

## Running it

The notebook needs `duckdb`, `pandas` and `numpy`. It creates `Spectral_data.duckdb` in
the working directory and reads the Windows share directly, so a local run needs both
paths adjusted to a local copy of the CSVs. The committed file is not modified for such
runs; a copy of the parsing code is enough, because `parse_file` has no database
dependency.

## Evaluation

`parser-evaluation.md` records what happened when the notebook was run against the
spectral files available locally, including the layout differences between the 2018
and 2025+ exports and how the output compares with `ingestion/spectral.py`.
