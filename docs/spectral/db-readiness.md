# Can the database hold the spectral data?

Answer to the question "does the DB already have everything necessary to accommodate
spectral data". This is a review of the schema and the ingestion path against what is
actually in the spectral files; the two files in `data/spectral_data/` were used as the
reference (see `parser-evaluation.md`).

No live database was available while this was written (no Docker in this environment),
so the check is static: migrations `V19`, `V20`, `V35`, `V39`, `V43`, the ingestion
code, and a check that the parameter adaptation used by `psycopg2` produces values
PostgreSQL accepts. The last live step — applying the migrations and inserting a real
file — still has to be done on the dev stack.

## What the schema provides

- `spectral_sensor` (V19) registers a sensor head: `name`, `model`, `instrument`,
  `serial_number`, `location`, and the wavelength axis `wavelengths_nm NUMERIC(7,2)[]`.
  It shares its primary key with the `sensor` supertype, so spectral sensors take part
  in `sensor_association_event` like any other sensor.
- `spectral_measurement` (V20) stores one row per (sensor, timestamp) with
  `irradiance_w_m2_um DOUBLE PRECISION[]`, plus `exposure_time_ms`, `sensor_temp_c` and
  `power_v`. It is a TimescaleDB hypertable on `timestamp` (renamed in V35), with a
  unique index on `(spectral_sensor_id, timestamp)`, which is what the
  `ON CONFLICT DO NOTHING` insert needs for idempotent re-runs.
- The irradiance array is aligned with the sensor's wavelength axis, and inactive
  wavelengths are stored as NaN, so both heads can share one table.
- `spectral_sensor` gets `last_update_time` and its trigger in V43, like the other
  registry tables.
- `ingestion_log` (V8) tracks files as `spectral:<YEAR>/<FILENAME>`, with a partial
  unique index that allows only one completed row per key.
- Everything the parsers read from the CSV header — date/time, exposure, sensor
  temperature, power, sensor model — has a column. `Memo` (the instrument name) is
  stored once per sensor as `instrument`.

So the numeric content of both file layouts fits without a schema change.

## Gaps and caveats

1. **Instrument name is per sensor, not per measurement.** `upsert_spectral_sensor`
   writes `instrument` when the sensor is first registered and never updates it. The
   2018 file says `EKO WISER`, the 2025+ files say `EKO WISER 35`; whichever is seen
   first wins, and the row then misstates the other files. Either normalise the name
   during parsing, or keep the instrument per measurement.
2. **Wavelength axis is written once.** `upsert_spectral_sensor` backfills
   `wavelengths_nm` only when it is still NULL. If a later file has a different axis
   (for example after fixing the 2025+ layout), the arrays are stored against the old
   axis without any check. Ingestion should verify the parsed axis equals the stored
   one and fail the file if not.
3. **`Merge` is stored as a third sensor head.** That follows the earlier decision to
   treat `Merge` as a sensor of its own, and the schema supports it, but it only exists
   in the 2018 files. Queries have to filter on `model`, and nothing marks the row as a
   derived quantity.
4. **No combined spectrum for 2025+ files.** The recipe in
   `docs/ingestion-patterns.md` sums MS-711 and MS-712 in the overlap, which roughly
   doubles the irradiance there; the instrument's own `Merge` column is not a sum
   either. This is a query/documentation question rather than a schema gap, but the
   current documented query gives wrong numbers.
5. **Timestamps.** `TIMESTAMPTZ` is the right type, but `ingestion/spectral.py` marks
   the file's naive times as UTC while every other parser treats naive times as
   `Europe/Berlin` and converts. The database cannot detect this, so it only shows up
   when spectra are compared with MPP or irradiance measurements.
6. **Storage size.** One measurement row carries the full 300–1800 nm axis: about
   12 kB of array data per row, roughly 2.5 GB per year for two heads at five-minute
   intervals before compression. No table in this database has a compression or
   retention policy yet, so spectral data is consistent with the rest; it is worth a
   separate look once historical ingestion starts.
7. **Deleting a sensor.** Measurement tables reference their sensor table without
   `ON DELETE CASCADE` (V39 only covers solar cell references), so removing a spectral
   sensor with measurements fails. Same behaviour as the temperature and irradiance
   tables; not a problem as long as sensors are not deleted.

## Verdict

The database is ready to store spectral data: it has a place for every value in the
files, a working idempotency key, and the registry and ingestion-log integration that
the other sensor types use. What is missing is on the ingestion side — the 2025+ layout
is rejected by the parser, the axis is not checked on later files, and the instrument
name and time zone assumptions need to be settled. No migration is required for the
data itself.
