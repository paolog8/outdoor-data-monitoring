-- V36's mpp_measurements_for_cell fails at call time with:
--   ERROR: column reference "timestamp" is ambiguous
-- RETURNS TABLE ("timestamp" ...) makes plpgsql declare an OUT parameter
-- named "timestamp"; the bare (unqualified) "timestamp" column reference in
-- the connection_intervals CTE then collides with it. Qualify it with the
-- CTE alias instead.

DROP FUNCTION mpp_measurements_for_cell(TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTERVAL);

CREATE FUNCTION mpp_measurements_for_cell(
    p_cell_name       TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    "timestamp"  TIMESTAMPTZ,
    mode_code    TEXT,
    voltage      DOUBLE PRECISION,
    current_a    DOUBLE PRECISION,
    power_mw     DOUBLE PRECISION
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF p_bucket_interval IS NULL THEN
        -- Raw path: unchanged behaviour
        RETURN QUERY
        WITH cell_events AS (
            SELECT
                e.event_type,
                e.mpp_tracking_slot_id,
                e.mode_id,
                e.timestamp,
                LEAD(e.timestamp) OVER (
                    PARTITION BY e.solar_cell_id
                    ORDER BY     e.timestamp
                ) AS interval_end
            FROM mpp_connection_event e
            WHERE e.solar_cell_id = (SELECT id FROM solar_cell WHERE name = p_cell_name)
        ),
        connection_intervals AS (
            SELECT
                mpp_tracking_slot_id,
                mode_id,
                cell_events.timestamp          AS interval_start,
                COALESCE(interval_end, NOW()) AS interval_end
            FROM cell_events
            WHERE event_type = 'connection'
        )
        SELECT
            m.timestamp,
            mcm.code      AS mode_code,
            m.voltage,
            m.current     AS current_a,
            m.power       AS power_mw
        FROM connection_intervals ci
        JOIN mpp_measurement m
            ON  m.mpp_tracking_slot_id = ci.mpp_tracking_slot_id
            AND m.timestamp >= ci.interval_start
            AND m.timestamp <  ci.interval_end
        JOIN mpp_connection_mode mcm ON mcm.id = ci.mode_id
        WHERE (p_start IS NULL OR m.timestamp >= p_start)
          AND (p_end   IS NULL OR m.timestamp <  p_end)
        ORDER BY m.timestamp;

    ELSE
        -- Bucketed path: one averaged row per time_bucket window
        RETURN QUERY
        WITH cell_events AS (
            SELECT
                e.event_type,
                e.mpp_tracking_slot_id,
                e.mode_id,
                e.timestamp,
                LEAD(e.timestamp) OVER (
                    PARTITION BY e.solar_cell_id
                    ORDER BY     e.timestamp
                ) AS interval_end
            FROM mpp_connection_event e
            WHERE e.solar_cell_id = (SELECT id FROM solar_cell WHERE name = p_cell_name)
        ),
        connection_intervals AS (
            SELECT
                mpp_tracking_slot_id,
                mode_id,
                cell_events.timestamp          AS interval_start,
                COALESCE(interval_end, NOW()) AS interval_end
            FROM cell_events
            WHERE event_type = 'connection'
        )
        SELECT
            time_bucket(p_bucket_interval, m.timestamp),
            MODE() WITHIN GROUP (ORDER BY mcm.code)         AS mode_code,
            AVG(m.voltage)  ::double precision               AS voltage,
            AVG(m.current)  ::double precision               AS current_a,
            AVG(m.power)    ::double precision               AS power_mw
        FROM connection_intervals ci
        JOIN mpp_measurement m
            ON  m.mpp_tracking_slot_id = ci.mpp_tracking_slot_id
            AND m.timestamp >= ci.interval_start
            AND m.timestamp <  ci.interval_end
        JOIN mpp_connection_mode mcm ON mcm.id = ci.mode_id
        WHERE (p_start IS NULL OR m.timestamp >= p_start)
          AND (p_end   IS NULL OR m.timestamp <  p_end)
        GROUP BY time_bucket(p_bucket_interval, m.timestamp)
        ORDER BY 1;

    END IF;
END;
$$;
