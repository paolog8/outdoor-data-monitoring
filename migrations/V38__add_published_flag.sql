-- Add published flag to the database
ALTER TABLE solar_cell ADD COLUMN published BOOLEAN DEFAULT FALSE;