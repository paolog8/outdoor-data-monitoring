-- Unique constraints on sensor serial_number needed for idempotent upserts in the
-- ingestion pipeline (ON CONFLICT ON CONSTRAINT ...).

ALTER TABLE temperature_sensor
    ADD CONSTRAINT uq_temperature_sensor_serial_number UNIQUE (serial_number);

ALTER TABLE irradiance_sensor
    ADD CONSTRAINT uq_irradiance_sensor_serial_number UNIQUE (serial_number);
