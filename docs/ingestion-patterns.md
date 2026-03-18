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
