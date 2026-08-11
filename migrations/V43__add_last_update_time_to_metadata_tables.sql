-- Add a last_update_time column to every metadata/registry table (i.e. every
-- table except the TimescaleDB measurement hypertables and ingestion_log,
-- which already has its own started_at/completed_at). Named to match the
-- last_update_time convention SymmetricDS itself uses on its sym_* config
-- tables.
--
-- The column defaults to now() so every row always has a value, and a
-- shared BEFORE UPDATE trigger refreshes it on every update regardless of
-- source (dashboard, ingestion pipeline, manual SQL). Because now() is a
-- volatile default, this backfills all pre-existing rows with the single
-- timestamp at which this migration runs, not their true historical
-- last-modified time -- that information was never tracked.

CREATE FUNCTION set_last_update_time()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.last_update_time := now();
    RETURN NEW;
END;
$$;

ALTER TABLE mpp_tracker ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_mpp_tracker_set_last_update_time
    BEFORE UPDATE ON mpp_tracker
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE mpp_tracking_slot ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_mpp_tracking_slot_set_last_update_time
    BEFORE UPDATE ON mpp_tracking_slot
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE sensor ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_sensor_set_last_update_time
    BEFORE UPDATE ON sensor
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE temperature_sensor ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_temperature_sensor_set_last_update_time
    BEFORE UPDATE ON temperature_sensor
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE irradiance_sensor ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_irradiance_sensor_set_last_update_time
    BEFORE UPDATE ON irradiance_sensor
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE spectral_sensor ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_spectral_sensor_set_last_update_time
    BEFORE UPDATE ON spectral_sensor
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE solar_cell ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_solar_cell_set_last_update_time
    BEFORE UPDATE ON solar_cell
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE solar_cell_group ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_solar_cell_group_set_last_update_time
    BEFORE UPDATE ON solar_cell_group
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE solar_cell_group_type ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_solar_cell_group_type_set_last_update_time
    BEFORE UPDATE ON solar_cell_group_type
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE solar_cell_type ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_solar_cell_type_set_last_update_time
    BEFORE UPDATE ON solar_cell_type
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE mpp_connection_mode ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_mpp_connection_mode_set_last_update_time
    BEFORE UPDATE ON mpp_connection_mode
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE mpp_polarity ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_mpp_polarity_set_last_update_time
    BEFORE UPDATE ON mpp_polarity
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE mpp_connection_event ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_mpp_connection_event_set_last_update_time
    BEFORE UPDATE ON mpp_connection_event
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE sensor_association_event ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_sensor_association_event_set_last_update_time
    BEFORE UPDATE ON sensor_association_event
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE scientist ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_scientist_set_last_update_time
    BEFORE UPDATE ON scientist
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE project ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_project_set_last_update_time
    BEFORE UPDATE ON project
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE experiment ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_experiment_set_last_update_time
    BEFORE UPDATE ON experiment
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE experiment_project ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_experiment_project_set_last_update_time
    BEFORE UPDATE ON experiment_project
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();

ALTER TABLE solar_cell_experiment ADD COLUMN last_update_time TIMESTAMPTZ NOT NULL DEFAULT now();
CREATE TRIGGER trg_solar_cell_experiment_set_last_update_time
    BEFORE UPDATE ON solar_cell_experiment
    FOR EACH ROW
    EXECUTE FUNCTION set_last_update_time();
