CREATE TABLE mpp_polarity (
    id   SERIAL PRIMARY KEY,
    code TEXT   NOT NULL UNIQUE
);

INSERT INTO mpp_polarity (code) VALUES
    ('positive'),
    ('negative'),
    ('automatic');

ALTER TABLE mpp_connection_event
    ADD COLUMN polarity_id INTEGER REFERENCES mpp_polarity(id);
