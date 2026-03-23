-- MPP data coverage summary views.
--
-- Slot-level views (mpp_slot_data_coverage, mpp_slot_data_coverage_summary):
--   Work immediately from mpp_measurement data; no cell assignment needed.
--   One row per (tracker, slot).
--
-- Cell-level views (mpp_data_coverage, mpp_data_coverage_summary):
--   Attribute measurements to solar cells via mpp_connection_event (same LEAD
--   approach as mpp_measurements_for_cell).  Returns data only once cells and
--   connection events have been entered.
--
-- In both cases: 2 slots/cells × 2 months monitored = 4 total slot/cell-months.


-- ---------------------------------------------------------------------------
-- Slot-level coverage
-- ---------------------------------------------------------------------------

CREATE VIEW mpp_slot_data_coverage AS
SELECT
    f.tracker_name,
    f.slot_code,
    MIN(f.time)                                            AS first_measurement,
    MAX(f.time)                                            AS last_measurement,
    MAX(f.time) - MIN(f.time)                              AS total_duration,
    ROUND(
        EXTRACT(EPOCH FROM (MAX(f.time) - MIN(f.time))) / 86400.0
    )::int                                                 AS total_days,
    ROUND(
        EXTRACT(EPOCH FROM (MAX(f.time) - MIN(f.time))) / 86400.0 / 30.44
    )::int                                                 AS total_months
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


-- ---------------------------------------------------------------------------
-- Cell-level coverage
-- ---------------------------------------------------------------------------

CREATE VIEW mpp_data_coverage AS
WITH connection_intervals AS (
    SELECT
        e.solar_cell_id,
        e.mpp_tracking_slot_id,
        e.occurred_at                                             AS interval_start,
        COALESCE(
            LEAD(e.occurred_at) OVER (
                PARTITION BY e.solar_cell_id
                ORDER BY     e.occurred_at
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
        MIN(m.time)                    AS first_meas,
        MAX(m.time)                    AS last_meas,
        MAX(m.time) - MIN(m.time)      AS duration
    FROM connection_intervals ci
    JOIN mpp_measurement m
        ON  m.mpp_tracking_slot_id = ci.mpp_tracking_slot_id
        AND m.time >= ci.interval_start
        AND m.time <  ci.interval_end
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
