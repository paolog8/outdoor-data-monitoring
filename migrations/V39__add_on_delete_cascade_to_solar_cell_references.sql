-- cascade delete solar cell references when the referenced solar cell is deleted

ALTER TABLE mpp_connection_event
    DROP CONSTRAINT mpp_connection_event_solar_cell_id_fkey,
    ADD CONSTRAINT mpp_connection_event_solar_cell_id_fkey
        FOREIGN KEY (solar_cell_id)
        REFERENCES solar_cell(id)
        ON DELETE CASCADE;

ALTER TABLE sensor_association_event
    DROP CONSTRAINT sensor_association_event_solar_cell_id_fkey,
    ADD CONSTRAINT sensor_association_event_solar_cell_id_fkey
        FOREIGN KEY (solar_cell_id)
        REFERENCES solar_cell(id)
        ON DELETE CASCADE;
        
ALTER TABLE solar_cell_group
    RENAME cell_id TO solar_cell_id;
    RENAME CONSTRAINT solar_cell_group_cell_id_fkey TO solar_cell_group_solar_cell_id_fkey;

ALTER TABLE solar_cell_group
    DROP CONSTRAINT solar_cell_group_solar_cell_id_fkey,
    ADD CONSTRAINT solar_cell_group_solar_cell_id_fkey
        FOREIGN KEY (solar_cell_id)
        REFERENCES solar_cell(id)
        ON DELETE CASCADE;

ALTER TABLE solar_cell_experiment
    DROP CONSTRAINT solar_cell_experiment_solar_cell_id_fkey,
    ADD CONSTRAINT solar_cell_experiment_solar_cell_id_fkey
        FOREIGN KEY (solar_cell_id)
        REFERENCES solar_cell(id)
        ON DELETE CASCADE;