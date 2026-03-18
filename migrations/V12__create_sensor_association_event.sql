-- Sensor Association Event log.
-- Append-only event log recording when any sensor starts or stops monitoring
-- a specific solar cell. References the sensor parent table, so it works for
-- all sensor types (temperature, irradiance, and any future types) without
-- schema changes.
-- Current association state is derived by querying the latest event for a
-- given solar_cell_id or sensor_id.

CREATE TABLE sensor_association_event (
    id             BIGSERIAL    PRIMARY KEY,
    event_type     TEXT         NOT NULL
                                    CHECK (event_type IN ('association', 'dissociation')),
    specification  TEXT,
    occurred_at    TIMESTAMPTZ  NOT NULL,
    solar_cell_id  BIGINT       NOT NULL REFERENCES solar_cell(id),
    sensor_id      BIGINT       NOT NULL REFERENCES sensor(id)
);

-- Efficiently find which sensor(s) were monitoring a given cell at a point in time
CREATE INDEX idx_sensor_association_event_cell_time
    ON sensor_association_event (solar_cell_id, occurred_at DESC);

-- Efficiently find which cell a given sensor was monitoring at a point in time
CREATE INDEX idx_sensor_association_event_sensor_time
    ON sensor_association_event (sensor_id, occurred_at DESC);
