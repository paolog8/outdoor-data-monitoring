-- Add additional identifier columns to solar_cell.
-- id_pvcomb: identifier assigned by the PVcomB facility.
-- id_alternative: additional identifier; seeded from existing name values
--   so that prior lab identifiers are preserved and queryable.
-- nomad_entry_url: URL to the corresponding entry in the NOMAD metadata platform.

ALTER TABLE solar_cell
    ADD COLUMN id_pvcomb        TEXT,
    ADD COLUMN id_alternative   TEXT,
    ADD COLUMN nomad_entry_url  TEXT;

UPDATE solar_cell
    SET id_alternative = name;
