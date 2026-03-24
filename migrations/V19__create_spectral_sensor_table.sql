-- Spectral sensor registry (EKO WISER 35 heads: MS-711, MS-712).
-- id links to the sensor parent table (supertype), established in V5.
-- serial_number doubles as the unique key; for these sensors, serial_number = model name.
-- wavelengths_nm stores the fixed wavelength axis for this sensor, populated on first ingestion.

CREATE TABLE spectral_sensor (
    id              BIGINT           PRIMARY KEY REFERENCES sensor(id),
    name            TEXT             NOT NULL,
    model           TEXT             NOT NULL,       -- e.g. 'MS-711', 'MS-712'
    instrument      TEXT             NOT NULL,       -- e.g. 'EKO WISER 35'
    serial_number   TEXT             NOT NULL,
    location        TEXT,
    wavelengths_nm  NUMERIC(7, 2)[]  -- fixed wavelength axis, set on first ingestion
);

CREATE UNIQUE INDEX uq_spectral_sensor_serial ON spectral_sensor (serial_number);
