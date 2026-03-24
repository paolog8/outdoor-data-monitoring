-- Solar cell grouping: records parent-child relationships between solar cells.
-- A solar_cell_group represents a physical or logical entity that contains
-- one or more solar cells (e.g. a substrate yielding multiple pixels, a
-- tandem device whose sub-junctions are measured independently, a batch
-- from the same deposition run, or a module of series-connected cells).
--
-- Design notes:
-- - Groups are NOT solar cells themselves (except for the tandem edge case
--   handled via cell_id). This avoids polluting solar_cell with non-measurable
--   "virtual" rows.
-- - A cell belongs to at most one group (direct FK, not a junction table).
--   This keeps "find the parent of cell X" unambiguous.
-- - Membership is a static FK, not an event log. Parent-child relationships
--   are structural and permanent; the event-log pattern is reserved for
--   temporal state changes (connections, associations).
-- - Hierarchy depth is two levels (group → cell). A parent_group_id column
--   can be added to solar_cell_group in a future migration if deeper nesting
--   is ever needed.


-- ---------------------------------------------------------------------------
-- Lookup: solar_cell_group_type
-- ---------------------------------------------------------------------------
-- Follows the same pattern as mpp_connection_mode: a lookup table with a
-- unique code column. New types are added via INSERT, no schema migration needed.

CREATE TABLE solar_cell_group_type (
    id          BIGSERIAL   PRIMARY KEY,
    code        TEXT        NOT NULL,
    description TEXT
);

-- Machine key must be unique (used in application logic and queries)
CREATE UNIQUE INDEX uq_solar_cell_group_type_code
    ON solar_cell_group_type (code);

INSERT INTO solar_cell_group_type (code, description) VALUES
    ('substrate', 'Physical carrier substrate yielding multiple pixel cells from one fabrication run'),
    ('tandem',    'Multi-junction cell whose sub-cells can each be measured independently'),
    ('module',    'Series- or parallel-connected cell assembly'),
    ('batch',     'Logical grouping of cells from the same deposition or process run');


-- ---------------------------------------------------------------------------
-- solar_cell_group
-- ---------------------------------------------------------------------------
-- Named physical or logical entity containing one or more solar cells.
--
-- cell_id (nullable): for group_type = 'tandem', the solar_cell row that
-- represents the full device as a measurable cell. This allows the tandem
-- device to be both a group container and an independently tracked cell.
-- The FK is DEFERRABLE so the group and its representative cell can be
-- inserted in the same transaction without worrying about FK ordering.

CREATE TABLE solar_cell_group (
    id               BIGSERIAL   PRIMARY KEY,
    name             TEXT        NOT NULL,
    group_type_id    BIGINT      NOT NULL REFERENCES solar_cell_group_type(id),
    fabrication_date DATE,
    manufacturer_id  BIGINT      REFERENCES scientist(id),
    notes            TEXT,
    cell_id          BIGINT      REFERENCES solar_cell(id)
                                 DEFERRABLE INITIALLY DEFERRED
);

CREATE UNIQUE INDEX uq_solar_cell_group_name
    ON solar_cell_group (name);

CREATE INDEX ON solar_cell_group (group_type_id);
CREATE INDEX ON solar_cell_group (manufacturer_id);
CREATE INDEX ON solar_cell_group (cell_id);


-- ---------------------------------------------------------------------------
-- Extend solar_cell with group membership
-- ---------------------------------------------------------------------------
-- group_id: the group this cell belongs to. NULL means standalone.
-- position_in_group: free-form physical label within the group
--   (e.g. 'P1'..'P6' for substrate pixels, 'top'/'bottom' for tandem
--   sub-junctions). Nullable — can be left NULL if the cell name already
--   encodes position.

ALTER TABLE solar_cell
    ADD COLUMN group_id          BIGINT  REFERENCES solar_cell_group(id),
    ADD COLUMN position_in_group TEXT;

-- FK index for group membership joins
CREATE INDEX ON solar_cell (group_id);
