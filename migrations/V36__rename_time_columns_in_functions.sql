-- V35 renamed the underlying "time"/"occurred_at" columns to "timestamp" on:
--   irradiance_measurement, mpp_measurement, temperature_measurement,
--   spectral_measurement, sensor_association_event, mpp_connection_event
--
-- This migration updates every function/view that referenced those columns
-- by name so the schema keeps working. Views must be dropped and recreated
-- (not CREATE OR REPLACE) because a couple of them implicitly expose the
-- renamed column in their own output and Postgres does not allow renaming
-- view output columns in place. Dependent views are dropped/recreated in
-- dependency order.

DROP VIEW mpp_slot_data_coverage_summary;
DROP VIEW mpp_slot_data_coverage;
DROP VIEW mpp_data_coverage_summary;
DROP VIEW mpp_data_coverage;
DROP VIEW mpp_measurement_flat;

DROP FUNCTION mpp_measurements_for_cell(TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTERVAL);
DROP FUNCTION mpp_measurements_with_sensors_for_cell(TEXT, TIMESTAMPTZ, TIMESTAMPTZ, INTERVAL);
DROP FUNCTION mpp_connection_history(TEXT);
DROP FUNCTION mpp_tracker_status(TEXT, TIMESTAMPTZ);


-- ---------------------------------------------------------------------------
-- mpp_measurement_flat
-- ---------------------------------------------------------------------------

CREATE VIEW mpp_measurement_flat AS
SELECT
    m.timestamp,
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
-- mpp_measurements_for_cell
-- ---------------------------------------------------------------------------

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
                timestamp                     AS interval_start,
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
                timestamp                     AS interval_start,
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


-- ---------------------------------------------------------------------------
-- mpp_measurements_with_sensors_for_cell
-- ---------------------------------------------------------------------------

CREATE FUNCTION mpp_measurements_with_sensors_for_cell(
    p_cell_name       TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    "timestamp"     TIMESTAMPTZ,
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
                sae.timestamp,
                LEAD(sae.timestamp) OVER (
                    PARTITION BY sae.sensor_id
                    ORDER BY     sae.timestamp
                ) AS next_timestamp
            FROM sensor_association_event sae
            WHERE sae.solar_cell_id = v_cell_id
        ),
        sensor_intervals AS (
            SELECT
                se.sensor_id,
                s.sensor_type,
                se.timestamp                     AS interval_start,
                COALESCE(se.next_timestamp, NOW()) AS interval_end
            FROM sensor_events se
            JOIN sensor s ON s.id = se.sensor_id
            WHERE se.event_type = 'association'
        )
        SELECT
            mpp.timestamp,
            mpp.mode_code,
            mpp.voltage,
            mpp.current_a,
            mpp.power_mw,
            t.temperature AS temperature_c,
            i.irradiance  AS irradiance_w_m2
        FROM mpp
        LEFT JOIN sensor_intervals si_t
            ON  si_t.sensor_type = 'temperature'
            AND mpp.timestamp >= si_t.interval_start
            AND mpp.timestamp <  si_t.interval_end
        LEFT JOIN temperature_measurement t
            ON  t.temperature_sensor_id = si_t.sensor_id
            AND t.timestamp              = mpp.timestamp
        LEFT JOIN sensor_intervals si_i
            ON  si_i.sensor_type = 'irradiance'
            AND mpp.timestamp >= si_i.interval_start
            AND mpp.timestamp <  si_i.interval_end
        LEFT JOIN irradiance_measurement i
            ON  i.irradiance_sensor_id = si_i.sensor_id
            AND i.timestamp             = mpp.timestamp
        ORDER BY mpp.timestamp;

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
                sae.timestamp,
                LEAD(sae.timestamp) OVER (
                    PARTITION BY sae.sensor_id
                    ORDER BY     sae.timestamp
                ) AS next_timestamp
            FROM sensor_association_event sae
            WHERE sae.solar_cell_id = v_cell_id
        ),
        sensor_intervals AS (
            SELECT
                se.sensor_id,
                s.sensor_type,
                se.timestamp                     AS interval_start,
                COALESCE(se.next_timestamp, NOW()) AS interval_end
            FROM sensor_events se
            JOIN sensor s ON s.id = se.sensor_id
            WHERE se.event_type = 'association'
        ),
        temp_buckets AS (
            SELECT
                time_bucket(p_bucket_interval, t.timestamp) AS bucket,
                AVG(t.temperature)::double precision   AS temperature_c
            FROM sensor_intervals si
            JOIN temperature_measurement t ON t.temperature_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'temperature'
              AND t.timestamp >= si.interval_start
              AND t.timestamp <  si.interval_end
              AND (p_start IS NULL OR t.timestamp >= p_start)
              AND (p_end   IS NULL OR t.timestamp <  p_end)
            GROUP BY bucket
        ),
        irr_buckets AS (
            SELECT
                time_bucket(p_bucket_interval, i.timestamp) AS bucket,
                AVG(i.irradiance)::double precision    AS irradiance_w_m2
            FROM sensor_intervals si
            JOIN irradiance_measurement i ON i.irradiance_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'irradiance'
              AND i.timestamp >= si.interval_start
              AND i.timestamp <  si.interval_end
              AND (p_start IS NULL OR i.timestamp >= p_start)
              AND (p_end   IS NULL OR i.timestamp <  p_end)
            GROUP BY bucket
        )
        SELECT
            mpp.timestamp,
            mpp.mode_code,
            mpp.voltage,
            mpp.current_a,
            mpp.power_mw,
            tb.temperature_c,
            ib.irradiance_w_m2
        FROM mpp
        LEFT JOIN temp_buckets tb ON tb.bucket = mpp.timestamp
        LEFT JOIN irr_buckets  ib ON ib.bucket = mpp.timestamp
        ORDER BY mpp.timestamp;

    END IF;
END;
$$;


-- ---------------------------------------------------------------------------
-- mpp_connection_history
-- ---------------------------------------------------------------------------

CREATE FUNCTION mpp_connection_history(p_cell_name TEXT)
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
            e.timestamp,
            LEAD(e.timestamp) OVER (
                PARTITION BY e.solar_cell_id
                ORDER BY     e.timestamp
            ) AS next_timestamp
        FROM mpp_connection_event e
        WHERE e.solar_cell_id = (SELECT id FROM solar_cell WHERE name = p_cell_name)
    )
    SELECT
        s.slot_code,
        t.name        AS tracker_name,
        mcm.code      AS mode_code,
        ce.timestamp                                            AS connected_at,
        CASE WHEN ce.next_timestamp IS NOT NULL
             THEN ce.next_timestamp END                         AS disconnected_at,
        CASE WHEN ce.next_timestamp IS NOT NULL
             THEN ce.next_timestamp - ce.timestamp END          AS duration
    FROM cell_events ce
    JOIN mpp_tracking_slot   s   ON s.id   = ce.mpp_tracking_slot_id
    JOIN mpp_tracker         t   ON t.id   = s.mpp_tracker_id
    JOIN mpp_connection_mode mcm ON mcm.id = ce.mode_id
    WHERE ce.event_type = 'connection'
    ORDER BY ce.timestamp;
$$;


-- ---------------------------------------------------------------------------
-- mpp_tracker_status
-- ---------------------------------------------------------------------------

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
        CASE WHEN e.event_type = 'connection' THEN e.timestamp END
                                                                 AS connected_since,
        CASE WHEN e.event_type = 'connection' THEN mp.code  END  AS polarity_code
    FROM mpp_tracking_slot s
    JOIN mpp_tracker t
        ON  t.id   = s.mpp_tracker_id
        AND t.name = p_tracker_name
    LEFT JOIN LATERAL (
        SELECT event_type, solar_cell_id, mode_id, polarity_id, timestamp
        FROM   mpp_connection_event
        WHERE  mpp_tracking_slot_id = s.id
          AND  timestamp <= p_at
        ORDER BY timestamp DESC
        LIMIT 1
    ) e ON true
    LEFT JOIN solar_cell          sc  ON sc.id  = e.solar_cell_id
    LEFT JOIN mpp_connection_mode mcm ON mcm.id = e.mode_id
    LEFT JOIN mpp_polarity        mp  ON mp.id  = e.polarity_id
    ORDER BY s.slot_code;
$$;


-- ---------------------------------------------------------------------------
-- mpp_data_coverage / mpp_data_coverage_summary
-- ---------------------------------------------------------------------------

CREATE VIEW mpp_data_coverage AS
WITH connection_intervals AS (
    SELECT
        e.solar_cell_id,
        e.mpp_tracking_slot_id,
        e.timestamp                                               AS interval_start,
        COALESCE(
            LEAD(e.timestamp) OVER (
                PARTITION BY e.solar_cell_id
                ORDER BY     e.timestamp
            ),
            NOW()
        )                                                         AS interval_end
    FROM mpp_connection_event e
    WHERE e.event_type = 'connection'
),
interval_extents AS (
    SELECT
        ci.solar_cell_id,
        ci.interval_start,
        MIN(m.timestamp)                    AS first_meas,
        MAX(m.timestamp)                    AS last_meas,
        MAX(m.timestamp) - MIN(m.timestamp) AS duration
    FROM connection_intervals ci
    JOIN mpp_measurement m
        ON  m.mpp_tracking_slot_id = ci.mpp_tracking_slot_id
        AND m.timestamp >= ci.interval_start
        AND m.timestamp <  ci.interval_end
    GROUP BY ci.solar_cell_id, ci.interval_start
)
SELECT
    sc.name                                    AS cell_name,
    MIN(ie.first_meas)                         AS first_measurement,
    MAX(ie.last_meas)                          AS last_measurement,
    SUM(ie.duration)                           AS total_duration,
    ROUND(
        EXTRACT(EPOCH FROM SUM(ie.duration)) / 86400.0
    )::int                                     AS total_days,
    ROUND(
        EXTRACT(EPOCH FROM SUM(ie.duration)) / 86400.0 / 30.44
    )::int                                     AS total_months
FROM interval_extents ie
JOIN solar_cell sc ON sc.id = ie.solar_cell_id
GROUP BY sc.name
ORDER BY sc.name;


CREATE VIEW mpp_data_coverage_summary AS
SELECT
    COUNT(*)                    AS cells_with_data,
    MIN(first_measurement)      AS earliest_measurement,
    MAX(last_measurement)       AS latest_measurement,
    SUM(total_days)             AS total_cell_days,
    SUM(total_months)           AS total_cell_months
FROM mpp_data_coverage;


-- ---------------------------------------------------------------------------
-- mpp_slot_data_coverage / mpp_slot_data_coverage_summary
-- ---------------------------------------------------------------------------

CREATE VIEW mpp_slot_data_coverage AS
SELECT
    f.tracker_name,
    f.slot_code,
    MIN(f.timestamp)                                            AS first_measurement,
    MAX(f.timestamp)                                            AS last_measurement,
    MAX(f.timestamp) - MIN(f.timestamp)                         AS total_duration,
    ROUND(
        EXTRACT(EPOCH FROM (MAX(f.timestamp) - MIN(f.timestamp))) / 86400.0
    )::int                                                      AS total_days,
    ROUND(
        EXTRACT(EPOCH FROM (MAX(f.timestamp) - MIN(f.timestamp))) / 86400.0 / 30.44
    )::int                                                      AS total_months
FROM mpp_measurement_flat f
GROUP BY f.tracker_name, f.slot_code
ORDER BY f.tracker_name, f.slot_code;


CREATE VIEW mpp_slot_data_coverage_summary AS
SELECT
    COUNT(*)                AS slots_with_data,
    MIN(first_measurement)  AS earliest_measurement,
    MAX(last_measurement)   AS latest_measurement,
    SUM(total_days)         AS total_slot_days,
    SUM(total_months)       AS total_slot_months
FROM mpp_slot_data_coverage;
