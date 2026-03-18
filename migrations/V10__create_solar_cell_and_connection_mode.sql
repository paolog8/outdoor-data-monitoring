-- Solar Cell registry and MPP connection mode lookup table.
-- solar_cell is the registry of individual photovoltaic devices under test.
-- mpp_connection_mode is a lookup table of valid operating modes a cell can be
-- connected in. New modes can be added via INSERT without a schema migration.

CREATE TABLE solar_cell (
    id      BIGSERIAL   PRIMARY KEY,
    name    TEXT        NOT NULL
);

-- Human-readable lab ID must be unique
CREATE UNIQUE INDEX uq_solar_cell_name
    ON solar_cell (name);


CREATE TABLE mpp_connection_mode (
    id          BIGSERIAL   PRIMARY KEY,
    code        TEXT        NOT NULL,
    description TEXT
);

-- Machine key must be unique (used in application logic and queries)
CREATE UNIQUE INDEX uq_mpp_connection_mode_code
    ON mpp_connection_mode (code);

-- Seed with the three standard modes
INSERT INTO mpp_connection_mode (code, description) VALUES
    ('mpp_tracking',  'Maximum power point tracking'),
    ('short_circuit', 'Cell terminals shorted (measures Isc)'),
    ('open_circuit',  'Cell terminals open (measures Voc)');
