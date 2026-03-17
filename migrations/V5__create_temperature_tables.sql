-- Temperature Sensor registry and time-series measurements.
-- Each sensor produces a single stream of readings; measurements FK directly to sensor.

CREATE TABLE temperature_sensor (
    id              UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT    NOT NULL,
    model           TEXT    NOT NULL,
    serial_number   TEXT,
    location        TEXT
);

CREATE TABLE temperature_measurement (
    time                    TIMESTAMPTZ         NOT NULL,
    temperature_sensor_id   UUID                NOT NULL REFERENCES temperature_sensor(id),
    temperature             DOUBLE PRECISION    NOT NULL  -- °C
);

CREATE UNIQUE INDEX uq_temperature_measurement_sensor_time
    ON temperature_measurement (temperature_sensor_id, time);

SELECT create_hypertable('temperature_measurement', 'time');
