-- MPP Tracker
-- Represents a physical MPP (Maximum Power Point) tracker device.
-- slot_code_pattern is a free-form string that describes the structure of
-- slot_code values used in mpp_tracking_slot for this tracker model.

CREATE TABLE mpp_tracker (
    id                  UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT    NOT NULL,
    model               TEXT    NOT NULL,
    slot_code_pattern   TEXT
);
