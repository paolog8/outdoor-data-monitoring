-- measurements_for_experiment_wide: same data as measurements_for_experiment
-- (V41), reshaped to one row per timestamp instead of one row per
-- (timestamp, cell, series).
--
-- A true wide table (one power_<cell>/current_<cell>/... column per
-- cell/sensor) still isn't possible as a plain RETURNS TABLE — see V41's
-- comment, the column set depends on which cells/sensors are in the
-- experiment. The compromise here: keep the *rows* (timestamp) fixed and
-- fixed-shape (two columns), but pack the per-cell/series values for that
-- timestamp into a single JSONB column instead of a text blob. That keeps
-- this a normal queryable table function (works in psql, DBeaver, etc, and
-- can be filtered/joined in SQL), while psycopg2/pandas hand JSONB back as
-- a native dict, so client code gets a wide table in one step:
--
--   import pandas as pd
--   df = pd.read_sql(
--       "SELECT * FROM measurements_for_experiment_wide(%s, %s, %s, %s)",
--       conn, params=['Exp1', None, None, '1 minute'],
--   )
--   wide = pd.json_normalize(df['series']).set_index(df['timestamp'])
--
-- Bucketing (p_bucket_interval) matters here even more than in V41: without
-- it, different cells'/sensors' readings rarely share an exact timestamp,
-- so most rows would have only one key in `series` and the JSONB would be
-- sparse per row. Bucket to whatever resolution you need before widening.

CREATE FUNCTION measurements_for_experiment_wide(
    p_experiment_name TEXT,
    p_start           TIMESTAMPTZ DEFAULT NULL,
    p_end             TIMESTAMPTZ DEFAULT NULL,
    p_bucket_interval INTERVAL    DEFAULT NULL
)
RETURNS TABLE (
    "timestamp" TIMESTAMPTZ,
    series      JSONB
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        m."timestamp",
        jsonb_object_agg(m.cell_name || '_' || m.series_name, m.value)
    FROM measurements_for_experiment(p_experiment_name, p_start, p_end, p_bucket_interval) m
    GROUP BY m."timestamp"
    ORDER BY m."timestamp";
$$;
