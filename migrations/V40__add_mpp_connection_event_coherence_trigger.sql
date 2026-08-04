-- Enforce coherence of mpp_connection_event: for a given mpp_tracking_slot_id,
-- event_type must strictly alternate between 'connection' and 'disconnection'
-- when ordered by timestamp. This rejects e.g. two consecutive 'connection'
-- events for the same slot (connecting an already-connected channel), or a
-- backfilled event landing inside an already-resolved interval.
--
-- Only checks the immediate neighbors (by timestamp) of the row being
-- inserted/updated, on the assumption that history is coherent up to the
-- point this migration is applied.

CREATE FUNCTION check_mpp_connection_event_coherence()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_predecessor_type TEXT;
    v_successor_type   TEXT;
BEGIN
    SELECT event_type INTO v_predecessor_type
    FROM mpp_connection_event
    WHERE mpp_tracking_slot_id = NEW.mpp_tracking_slot_id
      AND id <> NEW.id
      AND timestamp <= NEW.timestamp
    ORDER BY timestamp DESC, id DESC
    LIMIT 1;

    IF v_predecessor_type IS NOT NULL AND v_predecessor_type = NEW.event_type THEN
        RAISE EXCEPTION
            'Incoherent mpp_connection_event: slot % already has a % event at or before %',
            NEW.mpp_tracking_slot_id, NEW.event_type, NEW.timestamp
            USING ERRCODE = '23514';
    END IF;

    SELECT event_type INTO v_successor_type
    FROM mpp_connection_event
    WHERE mpp_tracking_slot_id = NEW.mpp_tracking_slot_id
      AND id <> NEW.id
      AND timestamp >= NEW.timestamp
    ORDER BY timestamp ASC, id ASC
    LIMIT 1;

    IF v_successor_type IS NOT NULL AND v_successor_type = NEW.event_type THEN
        RAISE EXCEPTION
            'Incoherent mpp_connection_event: slot % already has a % event at or after %',
            NEW.mpp_tracking_slot_id, NEW.event_type, NEW.timestamp
            USING ERRCODE = '23514';
    END IF;

    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_check_mpp_connection_event_coherence
    BEFORE INSERT OR UPDATE ON mpp_connection_event
    FOR EACH ROW
    EXECUTE FUNCTION check_mpp_connection_event_coherence();