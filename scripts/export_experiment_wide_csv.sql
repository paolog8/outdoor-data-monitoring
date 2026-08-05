-- Pivot measurements_for_experiment() (V41) into a genuinely flat wide table
-- (real power_<cell>-style DOUBLE PRECISION columns), via the tablefunc
-- extension's crosstab().
--
-- Why not measurements_for_experiment_wide() (V42): that packs the per-row
-- values into a single JSONB column, which is fine for one-query client-side
-- consumption (psycopg2/pandas deserialize it to a dict automatically) but
-- repeats every column *name* as text on every single row when serialized
-- (e.g. to CSV) -- for a large export that text repetition bloats the
-- output. This script produces real typed columns instead, with column
-- names sent once, so it's the smaller/flatter option for exports (e.g. to
-- Excel, or anything that can't parse a JSON column).
--
-- Why this needs two steps: in Postgres (and SQL generally -- see also
-- SQL Server/Oracle PIVOT), a query's column list must be fixed BEFORE the
-- query runs, for every client (psql, DBeaver, psycopg2, JDBC, ...). There
-- is no single SQL statement that can return a dynamic, not-yet-known set of
-- columns -- crosstab() (like PIVOT elsewhere) requires the caller to
-- declare the output columns in the query itself. Since which cells/sensors
-- are in a given experiment isn't known until you've looked, that means:
-- discover the columns first, then declare them in a second query.
--
-- Both steps are PLAIN SQL -- no \gset, no psql-specific meta-commands --
-- so this works from any SQL client (psql, DBeaver, pgAdmin, ...), not just
-- the psql CLI.
--
-- Keep the experiment name / start / end / bucket interval IDENTICAL between
-- step 1 and step 2, or the column list won't match the data.
--
-- Bucketing (the '1 minute' below) is what makes the pivot dense rather than
-- mostly-NULL: different cells' MPP readings and different sensors are not
-- sampled simultaneously, so without bucketing almost every column in a wide
-- row would be NULL except the one series that happened to land on that
-- exact timestamp. Pick a bucket width matching what you actually need.

CREATE EXTENSION IF NOT EXISTS tablefunc;

-- ---------------------------------------------------------------------------
-- Step 1: discover the distinct cell/series columns for this experiment +
-- window. Run this, then copy the single text value it returns.
-- ---------------------------------------------------------------------------

SELECT string_agg(format('%I double precision', col), ', ' ORDER BY col) AS coldefs
FROM (
    SELECT DISTINCT cell_name || '_' || series_name AS col
    FROM measurements_for_experiment('Exp1', NULL, NULL, '1 minute')
) t;

-- ---------------------------------------------------------------------------
-- Step 2: paste step 1's result in place of the placeholder line below
-- (replacing the whole `-- <PASTE coldefs HERE>` line), then run this query.
-- Its result set IS the wide table -- export it however your client
-- normally exports query results (DBeaver/pgAdmin "export resultset", or
-- `psql -c "...same query..." --csv > out.csv`, or `COPY (...) TO STDOUT
-- CSV HEADER` if you're in the psql CLI).
-- ---------------------------------------------------------------------------

SELECT * FROM crosstab(
    'SELECT timestamp, cell_name || ''_'' || series_name AS col, value
     FROM measurements_for_experiment(''Exp1'', NULL, NULL, ''1 minute'')
     ORDER BY 1, 2',
    'SELECT DISTINCT cell_name || ''_'' || series_name
     FROM measurements_for_experiment(''Exp1'', NULL, NULL, ''1 minute'')
     ORDER BY 1'
) AS ct(
    "timestamp" timestamptz,
    -- <PASTE coldefs HERE>
    placeholder double precision
)
ORDER BY 1;
