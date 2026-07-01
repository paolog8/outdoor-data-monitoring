-- Rename the measured_at output column to time on both mpp helper functions,
-- matching the column name used on the underlying tables (mpp_measurement.time,
-- temperature_measurement.time, irradiance_measurement.time, ...).
--
-- PostgreSQL does not allow CREATE OR REPLACE FUNCTION to rename RETURNS TABLE
-- columns, so both functions must be dropped and recreated.

DROP FUNCTION IF EXISTS mpp_measurements_for_cell(TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTERVAL);
DROP FUNCTION IF EXISTS mpp_measurements_with_sensors_for_cell(TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTERVAL);

CREATE FUNCTION mpp_measurements_for_cell(
    p_cell_name       TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    "time"       TIMESTAMPTZ,
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
            m.time,
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
            time_bucket(p_bucket_interval, m.time),
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
        ORDER BY 1;

    END IF;
END;
$$;


CREATE FUNCTION mpp_measurements_with_sensors_for_cell(
    p_cell_name       TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    "time"          TIMESTAMPTZ,
    mode_code       TEXT,
    voltage         DOUBLE PRECISION,
    current_a       DOUBLE PRECISION,
    power_mw        DOUBLE PRECISION,
    temperature_c   DOUBLE PRECISION,
    irradiance_w_m2 DOUBLE PRECISION
)
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    v_cell_id BIGINT := (SELECT id FROM solar_cell WHERE name = p_cell_name);
BEGIN
    IF p_bucket_interval IS NULL THEN
        -- Raw path: exact-timestamp sensor match per mpp reading
        RETURN QUERY
        WITH mpp AS (
            SELECT * FROM mpp_measurements_for_cell(p_cell_name, p_start, p_end)
        ),
        sensor_events AS (
            SELECT
                sae.event_type,
                sae.sensor_id,
                sae.occurred_at,
                LEAD(sae.occurred_at) OVER (
                    PARTITION BY sae.sensor_id
                    ORDER BY     sae.occurred_at
                ) AS next_occurred_at
            FROM sensor_association_event sae
            WHERE sae.solar_cell_id = v_cell_id
        ),
        sensor_intervals AS (
            SELECT
                se.sensor_id,
                s.sensor_type,
                se.occurred_at                     AS interval_start,
                COALESCE(se.next_occurred_at, NOW()) AS interval_end
            FROM sensor_events se
            JOIN sensor s ON s.id = se.sensor_id
            WHERE se.event_type = 'association'
        )
        SELECT
            mpp.time,
            mpp.mode_code,
            mpp.voltage,
            mpp.current_a,
            mpp.power_mw,
            t.temperature AS temperature_c,
            i.irradiance  AS irradiance_w_m2
        FROM mpp
        LEFT JOIN sensor_intervals si_t
            ON  si_t.sensor_type = 'temperature'
            AND mpp.time >= si_t.interval_start
            AND mpp.time <  si_t.interval_end
        LEFT JOIN temperature_measurement t
            ON  t.temperature_sensor_id = si_t.sensor_id
            AND t.time                  = mpp.time
        LEFT JOIN sensor_intervals si_i
            ON  si_i.sensor_type = 'irradiance'
            AND mpp.time >= si_i.interval_start
            AND mpp.time <  si_i.interval_end
        LEFT JOIN irradiance_measurement i
            ON  i.irradiance_sensor_id = si_i.sensor_id
            AND i.time                 = mpp.time
        ORDER BY mpp.time;

    ELSE
        -- Bucketed path: average sensor readings into the same buckets as mpp
        RETURN QUERY
        WITH mpp AS (
            SELECT * FROM mpp_measurements_for_cell(p_cell_name, p_start, p_end, p_bucket_interval)
        ),
        sensor_events AS (
            SELECT
                sae.event_type,
                sae.sensor_id,
                sae.occurred_at,
                LEAD(sae.occurred_at) OVER (
                    PARTITION BY sae.sensor_id
                    ORDER BY     sae.occurred_at
                ) AS next_occurred_at
            FROM sensor_association_event sae
            WHERE sae.solar_cell_id = v_cell_id
        ),
        sensor_intervals AS (
            SELECT
                se.sensor_id,
                s.sensor_type,
                se.occurred_at                     AS interval_start,
                COALESCE(se.next_occurred_at, NOW()) AS interval_end
            FROM sensor_events se
            JOIN sensor s ON s.id = se.sensor_id
            WHERE se.event_type = 'association'
        ),
        temp_buckets AS (
            SELECT
                time_bucket(p_bucket_interval, t.time) AS bucket,
                AVG(t.temperature)::double precision   AS temperature_c
            FROM sensor_intervals si
            JOIN temperature_measurement t ON t.temperature_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'temperature'
              AND t.time >= si.interval_start
              AND t.time <  si.interval_end
              AND (p_start IS NULL OR t.time >= p_start)
              AND (p_end   IS NULL OR t.time <  p_end)
            GROUP BY bucket
        ),
        irr_buckets AS (
            SELECT
                time_bucket(p_bucket_interval, i.time) AS bucket,
                AVG(i.irradiance)::double precision    AS irradiance_w_m2
            FROM sensor_intervals si
            JOIN irradiance_measurement i ON i.irradiance_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'irradiance'
              AND i.time >= si.interval_start
              AND i.time <  si.interval_end
              AND (p_start IS NULL OR i.time >= p_start)
              AND (p_end   IS NULL OR i.time <  p_end)
            GROUP BY bucket
        )
        SELECT
            mpp.time,
            mpp.mode_code,
            mpp.voltage,
            mpp.current_a,
            mpp.power_mw,
            tb.temperature_c,
            ib.irradiance_w_m2
        FROM mpp
        LEFT JOIN temp_buckets tb ON tb.bucket = mpp.time
        LEFT JOIN irr_buckets  ib ON ib.bucket = mpp.time
        ORDER BY mpp.time;

    END IF;
END;
$$;
