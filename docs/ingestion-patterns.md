# Ingestion Patterns

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
