# Sensor Data Model

## Design choice: supertype + concrete subtypes

Sensors are modelled using a **supertype/subtype** pattern:

- `sensor` — a single parent table that assigns a stable `id` and a `sensor_type` discriminator to every sensor regardless of its type.
- `temperature_sensor`, `irradiance_sensor`, … — concrete tables that share the parent's primary key (PK) (`id BIGINT PRIMARY KEY REFERENCES sensor(id)`) and carry all type-specific attributes (model, serial number, location, etc.).

```
sensor (id, sensor_type)
  ├── temperature_sensor (id → sensor.id, name, model, serial_number, location)
  └── irradiance_sensor  (id → sensor.id, name, model, serial_number, location)
```

### Why not a separate association table per sensor type?

The alternative — `temperature_sensor_association_event`, `irradiance_sensor_association_event`, … — was ruled out because:

1. **Unified association history.** The question "what was connected to this solar cell, and when?" is a single query against `sensor_association_event`. With per-type tables the query requires a UNION across all type tables, and that union must be updated every time a new sensor type is added.
2. **Schema stability.** Adding a new sensor type only requires creating a new concrete table. `sensor` and `sensor_association_event` are untouched.

### sensor_association_event

`sensor_association_event` is an **append-only event log**. It records each time a sensor starts (`association`) or stops (`dissociation`) monitoring a solar cell. Current state is derived from the most recent event for a given `(solar_cell_id, sensor_id)` pair — there is no separate "current state" table to keep in sync.

```
sensor_association_event
  id            BIGSERIAL PK
  event_type    TEXT  ('association' | 'dissociation')
  specification TEXT  (free-form notes)
  occurred_at   TIMESTAMPTZ
  solar_cell_id BIGINT → solar_cell.id
  sensor_id     BIGINT → sensor.id
```

A sensor may be associated with more than one solar cell at the same time. This is intentional.

Two indexes support the two natural access patterns:

| Index | Query it serves |
|---|---|
| `(solar_cell_id, occurred_at DESC)` | What sensor(s) were on cell X at time T? |
| `(sensor_id, occurred_at DESC)` | What cell was sensor S monitoring at time T? |

### Extending with a new sensor type

1. Insert a row into `sensor` to obtain an `id`.
2. Create a migration adding a `new_type_sensor` table with `id BIGINT PRIMARY KEY REFERENCES sensor(id)`.
3. No changes to `sensor_association_event` are needed — it already accepts any `sensor_id`.
