DROP FUNCTION mpp_tracker_status(TEXT, TIMESTAMPTZ);

CREATE FUNCTION mpp_tracker_status(
    p_tracker_name  TEXT,
    p_at            TIMESTAMPTZ DEFAULT NOW()
)
RETURNS TABLE (
    slot_code       TEXT,
    is_connected    BOOLEAN,
    cell_name       TEXT,        -- NULL if slot is empty
    mode_code       TEXT,        -- NULL if slot is empty
    connected_since TIMESTAMPTZ, -- NULL if slot is empty
    polarity_code   TEXT         -- NULL if slot is empty
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
                                                                 AS connected_since,
        CASE WHEN e.event_type = 'connection' THEN mp.code  END  AS polarity_code
    FROM mpp_tracking_slot s
    JOIN mpp_tracker t
        ON  t.id   = s.mpp_tracker_id
        AND t.name = p_tracker_name
    LEFT JOIN LATERAL (
        SELECT event_type, solar_cell_id, mode_id, polarity_id, occurred_at
        FROM   mpp_connection_event
        WHERE  mpp_tracking_slot_id = s.id
          AND  occurred_at <= p_at
        ORDER BY occurred_at DESC
        LIMIT 1
    ) e ON true
    LEFT JOIN solar_cell          sc  ON sc.id  = e.solar_cell_id
    LEFT JOIN mpp_connection_mode mcm ON mcm.id = e.mode_id
    LEFT JOIN mpp_polarity        mp  ON mp.id  = e.polarity_id
    ORDER BY s.slot_code;
$$;
