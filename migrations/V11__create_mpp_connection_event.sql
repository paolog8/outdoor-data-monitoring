-- MPP Connection Event log.
-- Append-only event log recording when a solar cell is connected to or
-- disconnected from an MPP tracking slot, and in what operating mode.
-- Current connection state is derived by querying the latest event for a
-- given solar_cell_id or mpp_tracking_slot_id.
--
-- Rules:
--   - event_type = 'connection'    => mode_id must be set
--   - event_type = 'disconnection' => mode_id must be NULL

CREATE TABLE mpp_connection_event (
    id                      BIGSERIAL   PRIMARY KEY,
    event_type              TEXT        NOT NULL
                                            CHECK (event_type IN ('connection', 'disconnection')),
    mode_id                 BIGINT      REFERENCES mpp_connection_mode(id),
    specification           TEXT,
    occurred_at             TIMESTAMPTZ NOT NULL,
    solar_cell_id           BIGINT      NOT NULL REFERENCES solar_cell(id),
    mpp_tracking_slot_id    BIGINT      NOT NULL REFERENCES mpp_tracking_slot(id),

    CONSTRAINT chk_connection_event_mode
        CHECK (
            (event_type = 'connection'    AND mode_id IS NOT NULL) OR
            (event_type = 'disconnection' AND mode_id IS NULL)
        )
);

-- Efficiently find latest event for a given cell (e.g., "is this cell currently connected?")
CREATE INDEX idx_mpp_connection_event_cell_time
    ON mpp_connection_event (solar_cell_id, occurred_at DESC);

-- Efficiently find latest event for a given slot (e.g., "what is in slot X right now?")
CREATE INDEX idx_mpp_connection_event_slot_time
    ON mpp_connection_event (mpp_tracking_slot_id, occurred_at DESC);
