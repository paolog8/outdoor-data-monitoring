-- Export measurements_for_experiment() (V41) as a wide CSV, pivoted entirely
-- server-side via the tablefunc extension's crosstab().
--
-- Why not pivot in pandas: measurements_for_experiment() returns long/tidy
-- rows (timestamp, cell_name, series_name, value) because the wide shape has
-- a column count that varies per experiment and can't be a fixed SQL return
-- type (see V41 migration comment / docs/ingestion-patterns.md). For a large
-- experiment the tidy form is ~4x the row count of the wide form (one row
-- per series instead of one row per timestamp), so exporting tidy CSV and
-- pivoting client-side means transferring and holding all of that redundancy
-- in memory just to throw most of it away. Doing the pivot in Postgres and
-- only streaming out the already-wide result avoids that entirely.
--
-- Usage: edit the experiment name / time window / bucket interval below
-- (the crosstab query text is a SQL string literal, so psql variables can't
-- be safely substituted into it without quoting hazards), then:
--
--   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
--     < scripts/export_experiment_wide_csv.sql > experiment_wide.csv
--
-- Must use plain "COPY ... TO STDOUT", not the \copy meta-command --
-- \copy does not perform :variable substitution inside its query text,
-- but ordinary SQL sent through psql does.
--
-- Bucketing (the '1 minute' below) is what makes the pivot dense rather than
-- mostly-NULL: different cells' MPP readings and different sensors are not
-- sampled simultaneously, so without bucketing almost every column in a wide
-- row would be NULL except the one series that happened to land on that
-- exact timestamp. Pick a bucket width matching what you actually need.

CREATE EXTENSION IF NOT EXISTS tablefunc;

-- 1. Discover the distinct cell/series columns for this experiment + window,
--    and build them into a `"col_name" double precision, ...` column-def
--    list for the crosstab() call below.
SELECT string_agg(format('%I double precision', col), ', ' ORDER BY col) AS coldefs
FROM (
    SELECT DISTINCT cell_name || '_' || series_name AS col
    FROM measurements_for_experiment('Exp1', NULL, NULL, '1 minute')
) t
\gset

-- 2. Pivot via crosstab() and stream the wide CSV to stdout.
--    Keep the experiment name / start / end / bucket interval identical to
--    step 1's query, or the column list won't match the data.
COPY (
    SELECT * FROM crosstab(
        'SELECT timestamp, cell_name || ''_'' || series_name AS col, value
         FROM measurements_for_experiment(''Exp1'', NULL, NULL, ''1 minute'')
         ORDER BY 1, 2',
        'SELECT DISTINCT cell_name || ''_'' || series_name
         FROM measurements_for_experiment(''Exp1'', NULL, NULL, ''1 minute'')
         ORDER BY 1'
    ) AS ct(timestamp timestamptz, :coldefs)
    ORDER BY 1
) TO STDOUT CSV HEADER;
