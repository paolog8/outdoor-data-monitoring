-- MPP Tracking Slot
-- Represents a physical input slot on an MPP tracker device.
-- slot_code is a device-specific structured string (format varies by tracker model,
-- e.g. a board/channel pair like 'B1-CH3', or just a channel like 'CH2').

CREATE TABLE mpp_tracking_slot (
    id              BIGSERIAL   PRIMARY KEY,
    slot_code       TEXT        NOT NULL,
    comments        TEXT,
    mpp_tracker_id  BIGINT      NOT NULL REFERENCES mpp_tracker(id)
);

-- Enforce unique slot codes within a tracker
CREATE UNIQUE INDEX uq_mpp_tracking_slot_tracker_code
    ON mpp_tracking_slot (mpp_tracker_id, slot_code);

-- Index for FK lookups (tracker → its slots)
CREATE INDEX idx_mpp_tracking_slot_tracker
    ON mpp_tracking_slot (mpp_tracker_id);
