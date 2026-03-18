-- MPP data access helpers.
-- Two objects bridge the gap between the hardware-centric schema and the
-- cell-centric view that scientists work with.
--
-- mpp_measurement_flat  : simple view — denormalizes tracker/slot names onto
--                         measurements for slot-level queries.
-- mpp_measurements_for_cell : table-returning function — returns all measurements
--                         attributed to a named solar cell, correctly scoped to
--                         the time intervals when that cell was connected.


-- ---------------------------------------------------------------------------
-- Layer 1: flat view
-- ---------------------------------------------------------------------------

CREATE VIEW mpp_measurement_flat AS
SELECT
    m.time,
    t.name        AS tracker_name,
    t.model       AS tracker_model,
    s.slot_code,
    s.id          AS mpp_tracking_slot_id,
    m.voltage,
    m.current,
    m.power
FROM mpp_measurement   m
JOIN mpp_tracking_slot s ON s.id = m.mpp_tracking_slot_id
JOIN mpp_tracker       t ON t.id = s.mpp_tracker_id;


-- ---------------------------------------------------------------------------
-- Layer 2: cell-attributed measurements
-- ---------------------------------------------------------------------------
-- Interval derivation (LEAD approach):
--   All events for the cell are ordered by occurred_at.  LEAD gives each
--   event the timestamp of the *next* event for that cell.  After filtering
--   to connection events only:
--     interval_end = next event's occurred_at   (normally a disconnection)
--                  = NOW()                       (cell still connected — LEAD is NULL)
--   This correctly handles cells that move between slots: the interval for the
--   first connection ends precisely when the second connection begins.

CREATE OR REPLACE FUNCTION mpp_measurements_for_cell(
    p_cell_name  TEXT,
    p_start      TIMESTAMPTZ DEFAULT NULL,
    p_end        TIMESTAMPTZ DEFAULT NULL
)
RETURNS TABLE (
    time       TIMESTAMPTZ,
    mode_code  TEXT,
    voltage    DOUBLE PRECISION,
    current    DOUBLE PRECISION,
    power      DOUBLE PRECISION
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
            ) AS interval_end
        FROM mpp_connection_event e
        WHERE e.solar_cell_id = (SELECT id FROM solar_cell WHERE name = p_cell_name)
    ),
    connection_intervals AS (
        SELECT
            mpp_tracking_slot_id,
            mode_id,
            occurred_at                   AS interval_start,
            COALESCE(interval_end, NOW()) AS interval_end
        FROM cell_events
        WHERE event_type = 'connection'
    )
    SELECT
        m.time,
        mcm.code  AS mode_code,
        m.voltage,
        m.current,
        m.power
    FROM connection_intervals ci
    JOIN mpp_measurement m
        ON  m.mpp_tracking_slot_id = ci.mpp_tracking_slot_id
        AND m.time >= ci.interval_start
        AND m.time <  ci.interval_end
    JOIN mpp_connection_mode mcm ON mcm.id = ci.mode_id
    WHERE (p_start IS NULL OR m.time >= p_start)
      AND (p_end   IS NULL OR m.time <  p_end)
    ORDER BY m.time;
$$;
