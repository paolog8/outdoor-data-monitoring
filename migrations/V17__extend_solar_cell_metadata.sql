-- Add metadata columns to solar_cell and create cell-experiment junction

ALTER TABLE solar_cell
    ADD COLUMN area_cm2         DOUBLE PRECISION,
    ADD COLUMN manufacturer_id  BIGINT REFERENCES scientist(id),
    ADD COLUMN owner_id         BIGINT REFERENCES scientist(id);

-- FK indexes for lookup joins
CREATE INDEX ON solar_cell (manufacturer_id);
CREATE INDEX ON solar_cell (owner_id);

-- Many-to-many: solar_cell ↔ experiment
CREATE TABLE solar_cell_experiment (
    solar_cell_id  BIGINT  NOT NULL REFERENCES solar_cell(id),
    experiment_id  BIGINT  NOT NULL REFERENCES experiment(id),
    PRIMARY KEY (solar_cell_id, experiment_id)
);
CREATE INDEX ON solar_cell_experiment (experiment_id);
