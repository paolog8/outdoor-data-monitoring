# Ingestion Patterns

## Pipeline architecture

The ingestion service (`ingestion/`) is split into one module per data type. `ingest.py` is the entry point and thin orchestrator; everything else is self-contained.

```
ingestion/
  constants.py     — shared constants and compiled regexes (BOARDS, CHANNELS, *_FILE_RE, …)
  db.py            — get_connection() — reads PG* env vars, returns a psycopg2 connection
  registry.py      — ensure_registry(), build_slot_map(), upsert_{temperature,irradiance,spectral}_sensor()
  mpp.py           — parse_file(), ingest_file(), ingest_mpp_folder()
  temperature.py   — parse_temperature_file(), ingest_temperature_measurements(), ingest_temperature_folder()
  irradiance.py    — parse_irradiance_file(), ingest_irradiance_measurements(), ingest_irradiance_folder()
  spectral.py      — parse_spectral_file(), ingest_spectral_measurements(), ingest_spectral_file(),
                     discover_pending_spectral_files()
  ingest.py        — discover_pending_folders(), process_folder(), main()
```

Each data-type module is fully self-contained: it owns its parser, its DB writer, and (if needed) its sensor-registry upsert. `ingest.py` imports the folder-level functions and wires them together inside `process_folder`.

## Adding a new sensor type

Work through these steps in order. Each step maps to exactly one file unless noted.

### 1. DB migration

Create a new Flyway migration (`V{N}__<description>.sql`) that adds:

- A subtype table inheriting from `sensor`:
  ```sql
  CREATE TABLE my_sensor (
      id            BIGINT PRIMARY KEY REFERENCES sensor(id),
      name          TEXT NOT NULL,
      model         TEXT,
      serial_number TEXT UNIQUE,   -- used as the upsert key
      ...
  );
  ```
- A hypertable for measurements:
  ```sql
  CREATE TABLE my_measurement (
      time          TIMESTAMPTZ NOT NULL,
      my_sensor_id  BIGINT NOT NULL REFERENCES my_sensor(id),
      value         DOUBLE PRECISION NOT NULL,
      ...
      UNIQUE (my_sensor_id, time)
  );
  SELECT create_hypertable('my_measurement', 'time');
  ```
- Any UNIQUE constraints or indexes needed for idempotent upserts.

### 2. constants.py — filename regex

Add a compiled regex that matches the new sensor's data files:

```python
MY_SENSOR_FILE_RE = re.compile(r"^my_device_(\w+)\.txt$")
```

Import it in the new module via `from constants import MY_SENSOR_FILE_RE`.

### 3. New module `my_sensor.py`

Create `ingestion/my_sensor.py` with three functions:

**`parse_my_sensor_file(file_path) -> list`**
Returns a list of tuples, one per data row. Skips malformed rows with `logger.warning`.
Follow the same TSV-reader pattern as `parse_temperature_file` in `temperature.py`.

**`ingest_my_sensor_measurements(cur, sensor_id, rows, batch_size, dry_run) -> int`**
Batch-inserts via `psycopg2.extras.execute_values` with `ON CONFLICT (my_sensor_id, time) DO NOTHING`.
Returns the row count actually written (`cur.rowcount`).

**`ingest_my_sensor_folder(conn, folder_path, batch_size, dry_run) -> int`**
Iterates the folder, matches filenames with `MY_SENSOR_FILE_RE`, calls the upsert (step 4),
parses, inserts in one transaction per file, rolls back and re-raises on failure.

### 4. registry.py — sensor upsert

Add `upsert_my_sensor(conn, serial_number) -> int`:

```python
def upsert_my_sensor(conn, serial_number: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM my_sensor WHERE serial_number = %s", (serial_number,))
        row = cur.fetchone()
        if row:
            return row[0]
        cur.execute("INSERT INTO sensor (sensor_type) VALUES ('my_sensor') RETURNING id")
        parent_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO my_sensor (id, name, serial_number) VALUES (%s, %s, %s) RETURNING id",
            (parent_id, f"my_device_{serial_number}", serial_number),
        )
        sensor_id = cur.fetchone()[0]
    conn.commit()
    return sensor_id
```

Import this in `my_sensor.py`: `from registry import upsert_my_sensor`.

### 5. ingest.py — wire into process_folder

Add one import and one line inside `process_folder`:

```python
from my_sensor import ingest_my_sensor_folder

# inside process_folder:
n += ingest_my_sensor_folder(conn, folder_path, batch_size, dry_run)
```

If the new sensor stores files outside the standard folder layout (like spectral), add a
`discover_pending_*` function in the new module and call it separately from `main()`.

### 6. Verify end-to-end

```bash
# Syntax check
python -m py_compile ingestion/my_sensor.py

# Dry run against real data (no DB writes)
DRY_RUN=true DATA_ROOT=/path/to/data docker compose run --rm ingestion

# Full run
DATA_ROOT=/path/to/data docker compose run --rm ingestion
```

Check `ingestion_log` for `status='completed'` entries and `rows_inserted > 0`.

---

## MPP Measurement

The `mpp_measurement` hypertable references `mpp_tracking_slot` by integer id. Since device data arrives identified by `(mpp_tracker_id, slot_code)` rather than an id, use the following single-statement pattern to resolve the slot and insert the measurement in one DB round trip — no application-side id lookup needed.

```sql
INSERT INTO mpp_measurement (time, mpp_tracking_slot_id, voltage, current, power)
SELECT
    $time,
    s.id,
    $voltage,
    $current,
    $power
FROM mpp_tracking_slot s
WHERE s.mpp_tracker_id = $tracker_id   -- BIGINT id of the tracker
  AND s.slot_code      = $slot_code;   -- e.g. 'PC01_board01_channel01'
```

This resolves via the unique index on `(mpp_tracker_id, slot_code)` — a fast, indexed lookup.

## Input file column order

MPP files (`output_board?_channel?.txt`) are tab-separated with columns:

```
timestamp    power [mW]    current [mA]    voltage [V]
```

Note: the DB insert order is `(voltage, current, power)` — reorder when mapping from file columns.

## Temperature ingestion

Temperature files (`m7004_ID_<hex>.txt`) are tab-separated with columns:

```
timestamp    temperature[°C]
```

Sensor identity comes from the hex serial number in the filename. Sensors are upserted into
`temperature_sensor` using `serial_number` as the unique key
(constraint `uq_temperature_sensor_serial_number`).

```sql
INSERT INTO temperature_measurement (time, temperature_sensor_id, temperature)
VALUES %s
ON CONFLICT (temperature_sensor_id, time) DO NOTHING;
```

## Irradiance ingestion

Irradiance files (`PT-104_channel_??.txt`) are tab-separated with columns:

```
timestamp    raw_value[uV]    irradiance[W/m²]
```

Sensor identity comes from the channel number in the filename (stored as `serial_number =
'channel_NN'`). Sensors are upserted into `irradiance_sensor` using `serial_number` as the
unique key (constraint `uq_irradiance_sensor_serial_number`).

```sql
INSERT INTO irradiance_measurement (time, irradiance_sensor_id, irradiance, raw_value)
VALUES %s
ON CONFLICT (irradiance_sensor_id, time) DO NOTHING;
```

## Spectral ingestion

Spectral files are EKO WISER 35 CSVs placed in `data/spectral_data/<YEAR>/<YYYYMMDDH*.CSV>`.
Each file contains one hour of measurements at 5-minute intervals for two sensor heads:
MS-711 (short wavelengths, ~300–1117 nm) and MS-712 (long wavelengths, ~882–1800 nm).

### File format

The CSV has 8 header rows followed by wavelength data:

```
Row 0: Date          — date value at odd columns (e.g. '2026/02/01'); even columns empty
Row 1: Time          — timestamp at odd columns; even columns empty
Row 2: Memo          — instrument name ('EKO WISER 35')
Row 3: Sensor        — model name per column ('MS-711' or 'MS-712'), all 24 filled
Row 4: Exposure Time — integer ms per column
Row 5: Sensor Temp.  — float °C per column
Row 6: Power(V)      — float V per column
Row 7: Column labels
Row 8+: Data         — col 0 = wavelength (nm); cols 1–24 = irradiance (W/m²/µm) or empty
```

Columns 1–24 represent 12 timestamps × 2 sensors, interleaved: MS-711, MS-712, MS-711, MS-712, …

Empty cells indicate that a wavelength is outside the sensor's active range and are not stored.

### Storage model

The **wavelength axis** is a hardware property of each sensor and is stored once in `spectral_sensor.wavelengths_nm[]` on first ingestion. Each measurement row stores only the aligned irradiance array:

```
spectral_sensor:     wavelengths_nm = [300.00, 301.00, ..., 1117.00]   (MS-711 example)
spectral_measurement: irradiance_w_m2_um = [0.37, 0.47, ..., 6.92]    (one array per timestamp)
```

Sensor identity is determined by model name (serial_number = model name), so there is one
`spectral_sensor` row per sensor head.

```sql
INSERT INTO spectral_measurement
    (time, spectral_sensor_id, irradiance_w_m2_um, exposure_time_ms, sensor_temp_c, power_v)
VALUES %s
ON CONFLICT (spectral_sensor_id, time) DO NOTHING;
```

### Reconstruct a spectrum from stored arrays

```sql
-- Full spectrum for both sensors at a given timestamp
SELECT s.model, w.wavelength_nm, m.irr
FROM spectral_measurement m
JOIN spectral_sensor s ON s.id = m.spectral_sensor_id
JOIN LATERAL unnest(s.wavelengths_nm, m.irradiance_w_m2_um) AS w(wavelength_nm, irr) ON true
WHERE m.time = '2026-02-01 12:00:00+00'
ORDER BY s.model, w.wavelength_nm;
```

### Combined spectrum (sum in overlap region)

MS-711 and MS-712 overlap between ~882–1117 nm. The combined spectrum is computed at query time
by summing both sensors' irradiance values at each shared wavelength:

```sql
SELECT wavelength_nm, SUM(irr) AS combined_irradiance_w_m2_um
FROM spectral_measurement m
JOIN spectral_sensor s ON s.id = m.spectral_sensor_id
JOIN LATERAL unnest(s.wavelengths_nm, m.irradiance_w_m2_um) AS w(wavelength_nm, irr) ON true
WHERE m.time = '2026-02-01 12:00:00+00'
GROUP BY wavelength_nm
ORDER BY wavelength_nm;
```

### Ingestion tracking

Spectral files are tracked in `ingestion_log` using keys of the form `spectral:<YEAR>/<FILENAME>`
(e.g. `spectral:2026/2026020112.CSV`). This namespaces them from folder-based MPP/temperature/
irradiance keys in the same table.

## Querying measurements for a solar cell

### What the function does

`mpp_measurements_for_cell` hides the complexity of the hardware schema. MPP data is stored per tracker slot, not per cell — and a cell can move between slots over time. The function automatically finds every interval when the named cell was connected, scopes the measurements to those intervals, and returns them in a single result set. You never need to know which slot a cell was on.

```sql
-- Every measurement ever taken for 'Cell_A'
SELECT * FROM mpp_measurements_for_cell('Cell_A');

-- Restrict to a time window
SELECT * FROM mpp_measurements_for_cell('Cell_A', '2024-06-01', '2024-07-01');
```

### Output columns

| Column | Type | Meaning |
|---|---|---|
| `measured_at` | `TIMESTAMPTZ` | Timestamp of the measurement (or bucket start when downsampling) |
| `mode_code` | `TEXT` | Connection mode: `'mpp_tracking'`, `'short_circuit'`, or `'open_circuit'` |
| `voltage` | `DOUBLE PRECISION` | Voltage in Volts |
| `current_a` | `DOUBLE PRECISION` | Current in Amps |
| `power_mw` | `DOUBLE PRECISION` | Power in milliWatts |

### Downsampling with `time_bucket`

Raw data can be collected at high frequency (e.g. every second). For plots or exports covering hours or days, returning every raw point is slow and more data than you need.

TimescaleDB provides `time_bucket(interval, timestamp)`, which works like rounding a timestamp down to the nearest fixed boundary:

```
time_bucket('1 hour',    '2024-06-15 14:37:22+00')  →  '2024-06-15 14:00:00+00'
time_bucket('5 minutes', '2024-06-15 14:37:22+00')  →  '2024-06-15 14:35:00+00'
```

All raw rows that land in the same bucket are grouped together and averaged. The function accepts an optional fourth argument `p_bucket_interval` that activates this mode:

```sql
-- One averaged row per minute
SELECT * FROM mpp_measurements_for_cell('Cell_A', '2024-06-01', '2024-06-02', '1 minute');

-- One averaged row per hour
SELECT * FROM mpp_measurements_for_cell('Cell_A', '2024-06-01', '2024-07-01', '1 hour');

-- One averaged row per day
SELECT * FROM mpp_measurements_for_cell('Cell_A', '2024-01-01', '2025-01-01', '1 day');

-- 10-second buckets, no time window restriction
SELECT * FROM mpp_measurements_for_cell('Cell_A', p_bucket_interval => '10 seconds');
```

The last example uses a **named argument** (`p_bucket_interval => ...`) to skip the `p_start`/`p_end` positional arguments without having to supply them explicitly.

In bucketed mode:
- `measured_at` is the **start** of the bucket window, not the exact time of any individual measurement.
- `voltage`, `current_a`, `power_mw` are the **averages** of all raw values that fell in that window.
- `mode_code` is the **most frequent** mode in the window (almost always a single mode, but edge cases around reconnection events are handled gracefully).

### Choosing a bucket width

- Match the bucket width to your display resolution. A 24-hour plot with one point per pixel needs at most ~1000 buckets — `'1 minute'` or `'5 minutes'` is usually enough.
- Do not go smaller than your data collection interval. If data is recorded every 5 seconds, a `'1 second'` bucket would return the same data as raw with added overhead.
- Typical choices: `'10 seconds'` for real-time monitoring, `'1 minute'` for hourly views, `'1 hour'` for multi-day overviews, `'1 day'` for long-term trends.

---

## Solar cell and connection tracking

`solar_cell` and `mpp_connection_mode` are manually managed reference tables — they are not
populated by the ingestion pipeline.

`mpp_connection_event` is an append-only event log. Current connection state is always derived
by finding the latest event for a given cell or slot — there is no separate "current state" table.

### Derive current connection state

**What cell is currently in slot X?**

```sql
SELECT e.solar_cell_id, c.name, e.mode_id, m.code AS mode, e.specification, e.occurred_at
FROM mpp_connection_event e
JOIN solar_cell c ON c.id = e.solar_cell_id
LEFT JOIN mpp_connection_mode m ON m.id = e.mode_id
WHERE e.mpp_tracking_slot_id = $slot_id
ORDER BY e.occurred_at DESC
LIMIT 1;
-- Returns NULL (no rows) if no events exist, or check that event_type = 'connection'
-- to confirm the slot currently has a cell (not just disconnected).
```

**What slot is cell X currently connected to?**

```sql
SELECT e.mpp_tracking_slot_id, s.slot_code, e.mode_id, m.code AS mode, e.occurred_at
FROM mpp_connection_event e
JOIN mpp_tracking_slot s ON s.id = e.mpp_tracking_slot_id
LEFT JOIN mpp_connection_mode m ON m.id = e.mode_id
WHERE e.solar_cell_id = $cell_id
ORDER BY e.occurred_at DESC
LIMIT 1;
-- Check event_type = 'connection' to confirm cell is currently connected.
```

Both queries use the `(solar_cell_id, occurred_at DESC)` and `(mpp_tracking_slot_id, occurred_at DESC)`
indexes on `mpp_connection_event` respectively.

## Sensor association tracking

`sensor_association_event` is a manually managed append-only event log — not populated by the
ingestion pipeline. It links any sensor type to a solar cell via the `sensor` parent table.

Current association state is derived by finding the latest event, same pattern as
`mpp_connection_event`.

### Derive current sensor association

**Which temperature sensor is currently monitoring cell X?**

```sql
SELECT ts.name, ts.serial_number, e.specification, e.occurred_at
FROM sensor_association_event e
JOIN temperature_sensor ts ON ts.sensor_id = e.sensor_id
WHERE e.solar_cell_id = $cell_id
ORDER BY e.occurred_at DESC
LIMIT 1;
-- Check event_type = 'association' to confirm currently active.
```

Replace the JOIN with `irradiance_sensor` for irradiance sensor queries.

**All sensors (any type) currently associated with cell X:**

```sql
SELECT s.sensor_type, e.sensor_id, e.occurred_at
FROM sensor_association_event e
JOIN sensor s ON s.id = e.sensor_id
WHERE e.solar_cell_id = $cell_id
  AND e.event_type = 'association'
ORDER BY e.occurred_at DESC;
```

This cross-type query works without UNION because all sensor types share the `sensor` parent table.
