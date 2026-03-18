-- Sensor parent table (supertype).
-- Provides a single identity for any sensor type (temperature, irradiance, ...).
-- Each concrete sensor table (temperature_sensor, irradiance_sensor) holds a FK
-- back to this table, established at creation time in V6 and V7.
-- sensor_type is a free-form discriminator — new sensor types can be introduced
-- without a schema change here.

CREATE TABLE sensor (
    id           BIGSERIAL  PRIMARY KEY,
    sensor_type  TEXT       NOT NULL  -- e.g. 'temperature', 'irradiance'
);
