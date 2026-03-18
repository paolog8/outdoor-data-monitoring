-- MPP connection helpers.
--
-- mpp_connection_history  : full connection event log for a named solar cell,
--                           with paired connected/disconnected timestamps and duration.
-- mpp_tracker_status      : point-in-time snapshot of every slot on a named tracker —
--                           what cell is connected (if any), in what mode, since when.
--                           Defaults to NOW() but accepts any past timestamp.


-- ---------------------------------------------------------------------------
-- mpp_connection_history
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION mpp_connection_history(p_cell_name TEXT)
RETURNS TABLE (
    slot_code        TEXT,
    tracker_name     TEXT,
    mode_code        TEXT,
    connected_at     TIMESTAMPTZ,
    disconnected_at  TIMESTAMPTZ,  -- NULL if still connected
    duration         INTERVAL      -- NULL if still connected
)
LANGUAGE sql
STABLE
AS $$
    WITH cell_events AS (
        SELECT
            e.event_type,
            e.mpp_tracking_slot_id,
            e.mode_id,
            e.occurred_at,
            LEAD(e.occurred_at) OVER (
                PARTITION BY e.solar_cell_id
                ORDER BY     e.occurred_at
            ) AS next_occurred_at
        FROM mpp_connection_event e
        WHERE e.solar_cell_id = (SELECT id FROM solar_cell WHERE name = p_cell_name)
    )
    SELECT
        s.slot_code,
        t.name        AS tracker_name,
        mcm.code      AS mode_code,
        ce.occurred_at                                          AS connected_at,
        CASE WHEN ce.next_occurred_at IS NOT NULL
             THEN ce.next_occurred_at END                       AS disconnected_at,
        CASE WHEN ce.next_occurred_at IS NOT NULL
             THEN ce.next_occurred_at - ce.occurred_at END      AS duration
    FROM cell_events ce
    JOIN mpp_tracking_slot   s   ON s.id   = ce.mpp_tracking_slot_id
    JOIN mpp_tracker         t   ON t.id   = s.mpp_tracker_id
    JOIN mpp_connection_mode mcm ON mcm.id = ce.mode_id
    WHERE ce.event_type = 'connection'
    ORDER BY ce.occurred_at;
$$;


-- ---------------------------------------------------------------------------
-- mpp_tracker_status
-- ---------------------------------------------------------------------------
-- For each slot on the named tracker, finds the most recent connection event
-- with occurred_at <= p_at using a LATERAL subquery (hits the
-- idx_mpp_connection_event_slot_time index on (mpp_tracking_slot_id, occurred_at DESC)).
-- Slots with no events, or whose last event was a disconnection, are shown with
-- is_connected = false and NULL metadata columns.
--
-- Note: mpp_tracker has a UNIQUE constraint on (name, model), not on name alone.
-- If two trackers share the same name, this function returns no rows.

CREATE OR REPLACE FUNCTION mpp_tracker_status(
    p_tracker_name  TEXT,
    p_at            TIMESTAMPTZ DEFAULT NOW()
)
RETURNS TABLE (
    slot_code       TEXT,
    is_connected    BOOLEAN,
    cell_name       TEXT,        -- NULL if slot is empty
    mode_code       TEXT,        -- NULL if slot is empty
    connected_since TIMESTAMPTZ  -- NULL if slot is empty
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        s.slot_code,
        (e.event_type = 'connection')                            AS is_connected,
        CASE WHEN e.event_type = 'connection' THEN sc.name  END  AS cell_name,
        CASE WHEN e.event_type = 'connection' THEN mcm.code END  AS mode_code,
        CASE WHEN e.event_type = 'connection' THEN e.occurred_at END
                                                                 AS connected_since
    FROM mpp_tracking_slot s
    JOIN mpp_tracker t
        ON  t.id   = s.mpp_tracker_id
        AND t.name = p_tracker_name
    LEFT JOIN LATERAL (
        SELECT event_type, solar_cell_id, mode_id, occurred_at
        FROM   mpp_connection_event
        WHERE  mpp_tracking_slot_id = s.id
          AND  occurred_at <= p_at
        ORDER BY occurred_at DESC
        LIMIT 1
    ) e ON true
    LEFT JOIN solar_cell          sc  ON sc.id  = e.solar_cell_id
    LEFT JOIN mpp_connection_mode mcm ON mcm.id = e.mode_id
    ORDER BY s.slot_code;
$$;
