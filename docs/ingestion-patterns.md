# Ingestion Patterns

## MPP Measurement

The `mpp_measurement` hypertable references `mpp_tracking_slot` by UUID. Since device data arrives identified by `(mpp_tracker_id, slot_code)` rather than a UUID, use the following single-statement pattern to resolve the slot and insert the measurement in one DB round trip — no application-side UUID lookup needed.

```sql
INSERT INTO mpp_measurement (time, mpp_tracking_slot_id, voltage, current, power)
SELECT
    $time,
    s.id,
    $voltage,
    $current,
    $power
FROM mpp_tracking_slot s
WHERE s.mpp_tracker_id = $tracker_id   -- UUID of the tracker device
  AND s.slot_code      = $slot_code;   -- e.g. 'CH1', 'B1-CH3'
```

This resolves via the unique index `uq_mpp_tracking_slot_tracker_code` on `(mpp_tracker_id, slot_code)` — a fast, indexed lookup.
