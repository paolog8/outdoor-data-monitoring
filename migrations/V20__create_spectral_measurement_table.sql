-- Spectral irradiance time-series. One row per (sensor, timestamp).
-- irradiance_w_m2_um is a 1-indexed array aligned with spectral_sensor.wavelengths_nm.
-- The array spans the full instrument wavelength axis; NaN marks wavelengths inactive for this sensor.
-- exposure_time_ms, sensor_temp_c, power_v are per-measurement metadata from the CSV header.

CREATE TABLE spectral_measurement (
    time                TIMESTAMPTZ         NOT NULL,
    spectral_sensor_id  BIGINT              NOT NULL REFERENCES spectral_sensor(id),
    irradiance_w_m2_um  DOUBLE PRECISION[]  NOT NULL,   -- W/m²/µm, aligned with sensor.wavelengths_nm
    exposure_time_ms    INTEGER,
    sensor_temp_c       DOUBLE PRECISION,
    power_v             DOUBLE PRECISION
);

SELECT create_hypertable('spectral_measurement', 'time');

CREATE UNIQUE INDEX uq_spectral_measurement_sensor_time
    ON spectral_measurement (spectral_sensor_id, time);
