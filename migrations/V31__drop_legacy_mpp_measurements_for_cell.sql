-- Drop the legacy 3-argument mpp_measurements_for_cell overload.
--
-- V14 created mpp_measurements_for_cell(TEXT, TIMESTAMPTZ, TIMESTAMPTZ).
-- V25 added a 4-argument version (..., INTERVAL DEFAULT NULL) for optional
-- downsampling. Because the new 4th argument carries a DEFAULT, that
-- CREATE OR REPLACE did NOT replace the 3-arg function — it created a second
-- overload alongside it.
--
-- Consequence: any 3-argument call is ambiguous between the two overloads
-- (the 3-arg matches exactly; the 4-arg matches via its default), producing:
--   ERROR: function mpp_measurements_for_cell(unknown, unknown, unknown) is not unique  (42725)
--
-- The 4-arg version with p_bucket_interval = NULL is behaviourally identical to
-- the old 3-arg version (same RETURNS TABLE columns, same raw query path), so the
-- 3-arg overload is redundant. Dropping it leaves a single function; all 1-, 2-,
-- and 3-argument calls then resolve unambiguously to the 4-arg function via its
-- defaults.

DROP FUNCTION IF EXISTS mpp_measurements_for_cell(TEXT, TIMESTAMPTZ, TIMESTAMPTZ);
