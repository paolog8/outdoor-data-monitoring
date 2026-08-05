-- measurements_for_experiment: all MPP + sensor measurements for every solar
-- cell in a named experiment, in long ("tidy") format rather than one wide
-- row per timestamp.
--
-- A wide shape (one power_<cell>/current_<cell>/voltage_<cell> column set per
-- cell, plus one <sensor>_<quantity> column per associated sensor) isn't
-- expressible as a plain SQL function: RETURNS TABLE needs a fixed column
-- list, but which cells (and which sensors) belong to an experiment varies
-- over time and across experiments. So this returns one row per
-- (timestamp, cell, series) instead:
--
--   timestamp   | cell_name | series_name              | value
--   ------------+-----------+--------------------------+-------
--   ...         | Cell_A    | power                    | ...
--   ...         | Cell_A    | current                  | ...
--   ...         | Cell_A    | voltage                  | ...
--   ...         | Cell_A    | TempSensor01_temperature | ...
--   ...         | Cell_B    | power                    | ...
--
-- series_name for sensor readings is "<sensor name>_<quantity>" (not just
-- the quantity) because a cell's associated sensor can change over time
-- (sensor_association_event), so different time ranges for the same cell
-- may legitimately come from different physical sensors.
--
-- Client code (e.g. the Dash dashboard, via pandas) can pivot this into the
-- originally-requested wide shape with
--   df.pivot_table(index='timestamp', columns=['cell_name', 'series_name'], values='value')
-- Note raw MPP readings and raw sensor readings are NOT necessarily on the
-- same clock (tracker slots are sampled sequentially, sensors on their own
-- interval), and different cells' MPP readings aren't necessarily
-- simultaneous either. Pivoting raw (p_bucket_interval IS NULL) output to
-- wide will therefore be sparse. Pass p_bucket_interval to get one
-- averaged row per time_bucket, aligned across all cells/sensors, which is
-- what you want for any multi-cell wide comparison.
--
-- Spectral sensors are excluded, same reasoning as
-- mpp_measurements_with_sensors_for_cell (V32): array-valued, doesn't fit
-- a single `value` column.

CREATE FUNCTION measurements_for_experiment(
    p_experiment_name TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    "timestamp" TIMESTAMPTZ,
    cell_name   TEXT,
    series_name TEXT,
    value       DOUBLE PRECISION
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    IF p_bucket_interval IS NULL THEN
        -- Raw path: every reading, on its own native timestamp
        RETURN QUERY
        WITH experiment_cells AS (
            SELECT sc.id AS solar_cell_id, sc.name AS cell_name
            FROM solar_cell_experiment sce
            JOIN solar_cell sc ON sc.id = sce.solar_cell_id
            JOIN experiment e  ON e.id  = sce.experiment_id
            WHERE e.name = p_experiment_name
        ),
        mpp_raw AS (
            SELECT m."timestamp", ec.cell_name, s.series_name, s.value
            FROM experiment_cells ec
            CROSS JOIN LATERAL mpp_measurements_for_cell(ec.cell_name, p_start, p_end) m
            CROSS JOIN LATERAL (VALUES
                ('power',   m.power_mw),
                ('current', m.current_a),
                ('voltage', m.voltage)
            ) AS s(series_name, value)
        ),
        sensor_events AS (
            SELECT
                ec.cell_name,
                sae.event_type,
                sae.sensor_id,
                sae."timestamp",
                LEAD(sae."timestamp") OVER (
                    PARTITION BY sae.sensor_id
                    ORDER BY     sae."timestamp"
                ) AS next_timestamp
            FROM experiment_cells ec
            JOIN sensor_association_event sae ON sae.solar_cell_id = ec.solar_cell_id
        ),
        sensor_intervals AS (
            SELECT
                se.cell_name,
                se.sensor_id,
                s.sensor_type,
                se."timestamp"                      AS interval_start,
                COALESCE(se.next_timestamp, NOW())  AS interval_end
            FROM sensor_events se
            JOIN sensor s ON s.id = se.sensor_id
            WHERE se.event_type = 'association'
        ),
        temp_raw AS (
            SELECT
                t."timestamp",
                si.cell_name,
                ts.name || '_temperature' AS series_name,
                t.temperature              AS value
            FROM sensor_intervals si
            JOIN temperature_sensor ts ON ts.id = si.sensor_id
            JOIN temperature_measurement t ON t.temperature_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'temperature'
              AND t."timestamp" >= si.interval_start
              AND t."timestamp" <  si.interval_end
              AND (p_start IS NULL OR t."timestamp" >= p_start)
              AND (p_end   IS NULL OR t."timestamp" <  p_end)
        ),
        irr_raw AS (
            SELECT
                i."timestamp",
                si.cell_name,
                irs.name || '_irradiance' AS series_name,
                i.irradiance               AS value
            FROM sensor_intervals si
            JOIN irradiance_sensor irs ON irs.id = si.sensor_id
            JOIN irradiance_measurement i ON i.irradiance_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'irradiance'
              AND i."timestamp" >= si.interval_start
              AND i."timestamp" <  si.interval_end
              AND (p_start IS NULL OR i."timestamp" >= p_start)
              AND (p_end   IS NULL OR i."timestamp" <  p_end)
        )
        SELECT * FROM mpp_raw
        UNION ALL
        SELECT * FROM temp_raw
        UNION ALL
        SELECT * FROM irr_raw
        ORDER BY 1, 2, 3;

    ELSE
        -- Bucketed path: one averaged row per (time_bucket, cell, series),
        -- so cells/sensors line up on a shared time grid for pivoting.
        RETURN QUERY
        WITH experiment_cells AS (
            SELECT sc.id AS solar_cell_id, sc.name AS cell_name
            FROM solar_cell_experiment sce
            JOIN solar_cell sc ON sc.id = sce.solar_cell_id
            JOIN experiment e  ON e.id  = sce.experiment_id
            WHERE e.name = p_experiment_name
        ),
        mpp_bucketed AS (
            SELECT m."timestamp", ec.cell_name, s.series_name, s.value
            FROM experiment_cells ec
            CROSS JOIN LATERAL mpp_measurements_for_cell(ec.cell_name, p_start, p_end, p_bucket_interval) m
            CROSS JOIN LATERAL (VALUES
                ('power',   m.power_mw),
                ('current', m.current_a),
                ('voltage', m.voltage)
            ) AS s(series_name, value)
        ),
        sensor_events AS (
            SELECT
                ec.cell_name,
                sae.event_type,
                sae.sensor_id,
                sae."timestamp",
                LEAD(sae."timestamp") OVER (
                    PARTITION BY sae.sensor_id
                    ORDER BY     sae."timestamp"
                ) AS next_timestamp
            FROM experiment_cells ec
            JOIN sensor_association_event sae ON sae.solar_cell_id = ec.solar_cell_id
        ),
        sensor_intervals AS (
            SELECT
                se.cell_name,
                se.sensor_id,
                s.sensor_type,
                se."timestamp"                      AS interval_start,
                COALESCE(se.next_timestamp, NOW())  AS interval_end
            FROM sensor_events se
            JOIN sensor s ON s.id = se.sensor_id
            WHERE se.event_type = 'association'
        ),
        temp_bucketed AS (
            SELECT
                time_bucket(p_bucket_interval, t."timestamp") AS "timestamp",
                si.cell_name,
                ts.name || '_temperature'                     AS series_name,
                AVG(t.temperature)::double precision           AS value
            FROM sensor_intervals si
            JOIN temperature_sensor ts ON ts.id = si.sensor_id
            JOIN temperature_measurement t ON t.temperature_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'temperature'
              AND t."timestamp" >= si.interval_start
              AND t."timestamp" <  si.interval_end
              AND (p_start IS NULL OR t."timestamp" >= p_start)
              AND (p_end   IS NULL OR t."timestamp" <  p_end)
            GROUP BY 1, si.cell_name, ts.name
        ),
        irr_bucketed AS (
            SELECT
                time_bucket(p_bucket_interval, i."timestamp") AS "timestamp",
                si.cell_name,
                irs.name || '_irradiance'                     AS series_name,
                AVG(i.irradiance)::double precision            AS value
            FROM sensor_intervals si
            JOIN irradiance_sensor irs ON irs.id = si.sensor_id
            JOIN irradiance_measurement i ON i.irradiance_sensor_id = si.sensor_id
            WHERE si.sensor_type = 'irradiance'
              AND i."timestamp" >= si.interval_start
              AND i."timestamp" <  si.interval_end
              AND (p_start IS NULL OR i."timestamp" >= p_start)
              AND (p_end   IS NULL OR i."timestamp" <  p_end)
            GROUP BY 1, si.cell_name, irs.name
        )
        SELECT * FROM mpp_bucketed
        UNION ALL
        SELECT * FROM temp_bucketed
        UNION ALL
        SELECT * FROM irr_bucketed
        ORDER BY 1, 2, 3;

    END IF;
END;
$$;
