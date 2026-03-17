-- MPP Measurement
-- Time-series readings (voltage, current, power) per MPP tracking slot.
-- Ingestion pattern: resolve slot via INSERT...SELECT using (mpp_tracker_id, slot_code)
-- to avoid application-side UUID lookups.

CREATE TABLE mpp_measurement (
    time                    TIMESTAMPTZ         NOT NULL,
    mpp_tracking_slot_id    UUID                NOT NULL REFERENCES mpp_tracking_slot(id),
    voltage                 DOUBLE PRECISION    NOT NULL,
    current                 DOUBLE PRECISION    NOT NULL,
    power                   DOUBLE PRECISION    NOT NULL
);

-- Prevent duplicate readings per slot per timestamp
CREATE UNIQUE INDEX uq_mpp_measurement_slot_time
    ON mpp_measurement (mpp_tracking_slot_id, time);

-- Convert to hypertable, partitioned by time
SELECT create_hypertable('mpp_measurement', 'time');
