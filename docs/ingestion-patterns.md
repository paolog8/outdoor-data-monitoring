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
