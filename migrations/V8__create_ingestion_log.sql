-- Needed by ensure_registry() to use ON CONFLICT for idempotent upsert
ALTER TABLE mpp_tracker
    ADD CONSTRAINT uq_mpp_tracker_name_model UNIQUE (name, model);

-- One row per folder attempt. Multiple 'started'/'failed' rows allowed; only one 'completed'.
CREATE TABLE ingestion_log (
    id            BIGSERIAL    PRIMARY KEY,
    folder_name   TEXT         NOT NULL,
    status        TEXT         NOT NULL CHECK (status IN ('started', 'completed', 'failed')),
    started_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    completed_at  TIMESTAMPTZ,
    rows_inserted INTEGER,
    error_message TEXT
);

-- Hard DB-level idempotency: a second 'completed' row for the same folder is rejected
CREATE UNIQUE INDEX uq_ingestion_log_folder_completed
    ON ingestion_log (folder_name)
    WHERE status = 'completed';

CREATE INDEX idx_ingestion_log_folder ON ingestion_log (folder_name);
