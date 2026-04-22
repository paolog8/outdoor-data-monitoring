# Solar Cell Data Model

## Solar cell registry

`solar_cell` is the registry of individual photovoltaic devices under test.

```
solar_cell
  id                BIGSERIAL PK
  name              TEXT  UNIQUE  — human-readable lab ID
  area_cm2          DOUBLE PRECISION
  manufacturer_id   BIGINT → scientist.id
  owner_id          BIGINT → scientist.id
  group_id          BIGINT → solar_cell_group.id  (NULL = standalone)
  position_in_group TEXT  (e.g. 'P1', 'top', NULL)
  id_pvcomb         TEXT  — identifier assigned by the PVcomB facility
  id_alternative    TEXT  — additional identifier; pre-populated from name for existing rows
  nomad_entry_url   TEXT  — URL to the corresponding NOMAD metadata entry
```

Cells can optionally be associated with experiments via the `solar_cell_experiment` junction table.

---

## Parent-child grouping

A `solar_cell_group` represents a physical or logical entity that contains one or more solar cells. Common cases:

| group_type | Example | Members |
|---|---|---|
| `substrate` | A glass substrate from one deposition run | 6 pixel cells (P1–P6) |
| `tandem` | A two-terminal perovskite/silicon tandem device | Top junction, bottom junction |
| `module` | A series-connected mini-module | Individual cell strings |
| `batch` | Cells from the same evaporation batch | Any cells sharing process conditions |

### Schema

```
solar_cell_group_type
  id           BIGSERIAL PK
  code         TEXT  UNIQUE  — machine key ('substrate', 'tandem', 'module', 'batch')
  description  TEXT

solar_cell_group
  id               BIGSERIAL PK
  name             TEXT  UNIQUE  — human-readable lab ID (e.g. 'SUB-2024-003')
  group_type_id    BIGINT → solar_cell_group_type.id
  fabrication_date DATE
  manufacturer_id  BIGINT → scientist.id
  notes            TEXT
  cell_id          BIGINT → solar_cell.id  — see tandem note below
```

`solar_cell.group_id` is the FK that records membership. A cell belongs to at most one group; `NULL` means it is standalone.

`solar_cell.position_in_group` is a free-form label for the cell's physical location within the group (e.g. `'P3'`, `'top'`). It is nullable — leave it `NULL` if the cell name already encodes position.

### Tandem edge case

A tandem device is simultaneously a *group container* (holding two sub-cell rows) and potentially a *measurable cell* in its own right (connectable to an MPP slot, associated with sensors). The `cell_id` column on `solar_cell_group` captures the back-reference to the `solar_cell` row representing the full device:

```
solar_cell:       id=42, name='TAN-001-full'          -- the full tandem, measured as-is
solar_cell_group: id=7,  name='TAN-001', cell_id=42   -- the group
solar_cell:       id=43, name='TAN-001-top',  group_id=7, position_in_group='top'
solar_cell:       id=44, name='TAN-001-bot',  group_id=7, position_in_group='bottom'
```

The `cell_id` FK is declared `DEFERRABLE INITIALLY DEFERRED`, so the group and its representative cell can be inserted in the same transaction without ordering constraints.

---

## Key design decisions

**Separate group table, not self-referential FK.** Substrates are not solar cells. Adding a `parent_id` to `solar_cell` would require every coverage view, connection function, and dashboard query to exclude non-measurable "virtual" parent rows. A dedicated `solar_cell_group` table cleanly separates the physical carrier from the measurable devices.

**Direct FK, not a junction table.** A cell belongs to at most one group. A junction table would allow multi-group membership and make "find the parent of cell X" ambiguous. If multi-membership is ever needed, a `solar_cell_group_member` junction table can be added alongside the existing FK.

**Static FK, not an event log.** Parent-child membership is structural and permanent. The append-only event-log pattern is reserved for temporal relationships (MPP connections, sensor associations).

**Two levels only.** Group → cell is sufficient for all current use cases. A `parent_group_id` column can be added to `solar_cell_group` in a future migration if modules-of-modules or deeper hierarchies are ever needed.

---

## Common queries

**All pixels on a substrate:**

```sql
SELECT sc.name, sc.position_in_group
FROM   solar_cell sc
JOIN   solar_cell_group g ON g.id = sc.group_id
WHERE  g.name = 'SUB-2024-003'
ORDER BY sc.position_in_group;
```

**Parent group of a cell:**

```sql
SELECT g.name        AS group_name,
       gt.code       AS group_type,
       g.fabrication_date
FROM   solar_cell sc
JOIN   solar_cell_group      g  ON g.id  = sc.group_id
JOIN   solar_cell_group_type gt ON gt.id = g.group_type_id
WHERE  sc.name = 'TAN-001-top';
```

**Siblings of a cell (other members of the same group):**

```sql
SELECT sibling.name, sibling.position_in_group
FROM   solar_cell target
JOIN   solar_cell sibling ON sibling.group_id = target.group_id
                          AND sibling.id      <> target.id
WHERE  target.name = 'TAN-001-top';
```

**All substrate groups with member count:**

```sql
SELECT g.name, g.fabrication_date, COUNT(sc.id) AS pixel_count
FROM   solar_cell_group      g
JOIN   solar_cell_group_type gt ON gt.id = g.group_type_id
LEFT JOIN solar_cell          sc ON sc.group_id = g.id
WHERE  gt.code = 'substrate'
GROUP BY g.id, g.name, g.fabrication_date
ORDER BY g.fabrication_date DESC NULLS LAST;
```

**All member cells and their current MPP connection state:**

```sql
WITH members AS (
    SELECT sc.id AS cell_id, sc.name AS cell_name, sc.position_in_group
    FROM   solar_cell sc
    JOIN   solar_cell_group g ON g.id = sc.group_id
    WHERE  g.name = 'SUB-2024-003'
)
SELECT
    m.cell_name,
    m.position_in_group,
    e.event_type,
    mcm.code AS mode_code,
    e.occurred_at
FROM members m
LEFT JOIN LATERAL (
    SELECT event_type, mode_id, occurred_at
    FROM   mpp_connection_event
    WHERE  solar_cell_id = m.cell_id
    ORDER BY occurred_at DESC
    LIMIT 1
) e ON true
LEFT JOIN mpp_connection_mode mcm ON mcm.id = e.mode_id
ORDER BY m.position_in_group;
```

---

## Adding a new group type

Insert a row into `solar_cell_group_type`; no schema migration is needed:

```sql
INSERT INTO solar_cell_group_type (code, description)
VALUES ('masked_cell', 'Aperture-masked cell for certified efficiency measurement');
```
