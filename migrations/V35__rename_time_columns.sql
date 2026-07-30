-- Rename all time columns to timestamp in: 
-- - irradiance_measurement  
-- - mpp_measurement         
-- - temperature_measurement 
-- - spectral_measurement    
-- - sensor_association_event
-- - mpp_connection_event    

ALTER TABLE irradiance_measurement RENAME COLUMN time TO timestamp;
ALTER TABLE mpp_measurement RENAME COLUMN time TO timestamp;
ALTER TABLE temperature_measurement RENAME COLUMN time TO timestamp;
ALTER TABLE spectral_measurement RENAME COLUMN time TO timestamp;

ALTER TABLE sensor_association_event RENAME COLUMN occurred_at TO timestamp;
ALTER TABLE mpp_connection_event RENAME COLUMN occurred_at TO timestamp;