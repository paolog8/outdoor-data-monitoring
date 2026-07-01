-- Replace the nearest-in-time LATERAL match in mpp_measurements_with_sensors_for_cell's
-- raw path with an exact-timestamp join. Sensors are sampled on the same clock as
-- mpp_measurement, so nearest-match was unnecessary complexity — an equality join
-- on time is simpler and behaves the same when clocks line up.

CREATE OR REPLACE FUNCTION mpp_measurements_with_sensors_for_cell(
    p_cell_name       TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    measured_at     TIMESTAMPTZ,
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
            mpp.measured_at,
            mpp.mode_code,
            mpp.voltage,
            mpp.current_a,
            mpp.power_mw,
            t.temperature AS temperature_c,
            i.irradiance  AS irradiance_w_m2
        FROM mpp
        LEFT JOIN sensor_intervals si_t
            ON  si_t.sensor_type = 'temperature'
            AND mpp.measured_at >= si_t.interval_start
            AND mpp.measured_at <  si_t.interval_end
        LEFT JOIN temperature_measurement t
            ON  t.temperature_sensor_id = si_t.sensor_id
            AND t.time                  = mpp.measured_at
        LEFT JOIN sensor_intervals si_i
            ON  si_i.sensor_type = 'irradiance'
            AND mpp.measured_at >= si_i.interval_start
            AND mpp.measured_at <  si_i.interval_end
        LEFT JOIN irradiance_measurement i
            ON  i.irradiance_sensor_id = si_i.sensor_id
            AND i.time                 = mpp.measured_at
        ORDER BY mpp.measured_at;

    ELSE
        -- Bucketed path: average sensor readings into the same buckets as mpp
        -- (unchanged from V32)
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
            mpp.measured_at,
            mpp.mode_code,
            mpp.voltage,
            mpp.current_a,
            mpp.power_mw,
            tb.temperature_c,
            ib.irradiance_w_m2
        FROM mpp
        LEFT JOIN temp_buckets tb ON tb.bucket = mpp.measured_at
        LEFT JOIN irr_buckets  ib ON ib.bucket = mpp.measured_at
        ORDER BY mpp.measured_at;

    END IF;
END;
$$;
