-- Irradiance Sensor registry and time-series measurements.
-- Each sensor produces a single stream of readings; measurements FK directly to sensor.
-- sensor_id links to the sensor parent table (supertype), established in V5.
-- raw_value stores the unconverted integer output from the sensor hardware.
-- irradiance stores the converted value in W/m².

CREATE TABLE irradiance_sensor (
    id              BIGINT      PRIMARY KEY REFERENCES sensor(id),
    name            TEXT        NOT NULL,
    model           TEXT        NOT NULL,
    serial_number   TEXT,
    location        TEXT
);

CREATE TABLE irradiance_measurement (
    time                    TIMESTAMPTZ         NOT NULL,
    irradiance_sensor_id    BIGINT              NOT NULL REFERENCES irradiance_sensor(id),
    irradiance              DOUBLE PRECISION    NOT NULL,  -- W/m² (converted)
    raw_value               INTEGER             NOT NULL   -- raw sensor output
);

CREATE UNIQUE INDEX uq_irradiance_measurement_sensor_time
    ON irradiance_measurement (irradiance_sensor_id, time);

SELECT create_hypertable('irradiance_measurement', 'time');
