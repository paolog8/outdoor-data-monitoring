-- Add optional downsampling to mpp_measurements_for_cell.
--
-- New fourth parameter p_bucket_interval INTERVAL DEFAULT NULL:
--   NULL  → raw rows, identical to previous behaviour
--   set   → one averaged row per time_bucket window
--
-- time_bucket() is a TimescaleDB function that floors timestamps to the
-- nearest fixed-width boundary, enabling GROUP BY aggregation per window.

CREATE OR REPLACE FUNCTION mpp_measurements_for_cell(
    p_cell_name       TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    measured_at  TIMESTAMPTZ,
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
            m.time        AS measured_at,
            mcm.code      AS mode_code,
            m.voltage,
            m.current     AS current_a,
            m.power       AS power_mw
        FROM connection_intervals ci
        JOIN mpp_measurement m
            ON  m.mpp_tracking_slot_id = ci.mpp_tracking_slot_id
            AND m.time >= ci.interval_start
            AND m.time <  ci.interval_end
        JOIN mpp_connection_mode mcm ON mcm.id = ci.mode_id
        WHERE (p_start IS NULL OR m.time >= p_start)
          AND (p_end   IS NULL OR m.time <  p_end)
        ORDER BY m.time;

    ELSE
        -- Bucketed path: one averaged row per time_bucket window
        RETURN QUERY
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
            time_bucket(p_bucket_interval, m.time)          AS measured_at,
            MODE() WITHIN GROUP (ORDER BY mcm.code)         AS mode_code,
            AVG(m.voltage)  ::double precision               AS voltage,
            AVG(m.current)  ::double precision               AS current_a,
            AVG(m.power)    ::double precision               AS power_mw
        FROM connection_intervals ci
        JOIN mpp_measurement m
            ON  m.mpp_tracking_slot_id = ci.mpp_tracking_slot_id
            AND m.time >= ci.interval_start
            AND m.time <  ci.interval_end
        JOIN mpp_connection_mode mcm ON mcm.id = ci.mode_id
        WHERE (p_start IS NULL OR m.time >= p_start)
          AND (p_end   IS NULL OR m.time <  p_end)
        GROUP BY time_bucket(p_bucket_interval, m.time)
        ORDER BY measured_at;

    END IF;
END;
$$;
