CREATE TABLE solar_cell_type (
    id   SERIAL PRIMARY KEY,
    code TEXT   NOT NULL UNIQUE
);

INSERT INTO solar_cell_type (code) VALUES
    ('Pero'),
    ('Pero-Organic'),
    ('Silicon'),
    ('CIGS-Pero Tandem'),
    ('Pero-Si Tandem'),
    ('Pero-Flexible');

ALTER TABLE solar_cell
    ADD COLUMN cell_type_id INTEGER REFERENCES solar_cell_type(id);
