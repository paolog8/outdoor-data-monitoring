# Outdoor PV Data Monitoring

Edge system running on the outdoor **measurement PC** at PVcomB. It ingests MPP-tracker,
temperature, irradiance, and spectral data exports into a local PostgreSQL + TimescaleDB
database, provides a Streamlit app for registering cells and recording
connection/teardown events, and replicates everything to the central hub server
(SymmetricDS), where scientists analyze it in Grafana.

```
data exports ──► ingestion (daily cron) ──► Postgres/TimescaleDB ──► SymmetricDS ──► hub
                                                   ▲
                            Streamlit dashboard ───┘  (registry + connection events)
```

## Services (`docker-compose.yml`)

| Service | Purpose |
|---|---|
| `postgres` | TimescaleDB (pg17), database `outdoor_monitoring`, port 5432 |
| `flyway` | Applies `migrations/` on startup (currently V1–V31) |
| `ingestion` | Cron container: runs `ingest.py` daily at 02:00 and once at startup |
| `dashboard` | Streamlit app on port 8501 (registry + events UI) |
| `symmetricds` | Edge replication node, pushes to the hub (port 31415) |

Secrets come from `.env` (not committed): `POSTGRES_DB/USER/PASSWORD`, `SYM_PASSWORD`,
`SYM_SERVER_ADDRESS/PORT`.

A local-development `docker-compose.override.yml` (gitignored) can disable the
replication services via profiles and inject proxy build args. **Never deploy it to the
measurement PC** — it would silently disable SymmetricDS.

## Data flow & ingestion

Measurement software periodically exports folders into `data/`:

- `data/mppt_temp_irr/data_YYYYMMDD/data/` — `output_board<N>_channel<M>.txt` (MPP),
  temperature, and irradiance files
- `data/spectral_data/` — spectral CSV files

The `ingestion` container scans for folders/files not yet marked `completed` in
`ingestion_log` and ingests them idempotently (UNIQUE constraints + upserts), so
re-runs are safe. Failures are recorded with `status='failed'` and an error message:

```sql
SELECT * FROM ingestion_log WHERE status = 'failed' ORDER BY started_at DESC;
```

To re-ingest a folder, delete (or update) its `ingestion_log` row and let the next cron
run pick it up, or run immediately:

```bash
docker compose run --rm ingestion python3 /app/ingest.py       # DRY_RUN=true to preview
```

See `docs/ingestion-patterns.md` for file formats and how to add a new sensor type.

## Dashboard (Streamlit, port 8501)

- **Overview** — system counts, tracker slot occupancy snapshot
- **Events** — connect cells to tracker slots (board/channel grid), associate sensors,
  teardown; supports batch entry and historical dates. A **Corrections** tab allows
  deleting the most recent event of a slot (with confirmation) to fix data-entry
  mistakes — older events are immutable by design.
- **Registry** — CRUD for scientists, cells (incl. type/structure/initial PCE), groups,
  experiments, sensors; batch cell registration and CSV import

Set `GRAFANA_BASE_URL` in `.env` (e.g. `https://<hub-host>`) to get "Open in Grafana"
deep-links from the cell edit form to the hub's Single Cell Deep-Dive dashboard.

All visualization/plotting happens in Grafana on the hub, not here.

## Database & migrations

Schema reference: `CLAUDE.md` (tables, event-log pattern, helper functions). Migrations
are Flyway-versioned SQL in `migrations/`, applied automatically on `docker compose up`.

**When adding a migration:** the hub repo keeps a copy under `db/outdoor_migrations/`
with version numbers offset by **+3** (it inserted its own early migrations). Append the
new file there with the offset number; never renumber existing files. Details in
`CLAUDE.md` ("Perocube replica divergence").

## Operations quick reference

```bash
docker compose up -d                  # start everything, apply migrations
docker compose logs -f ingestion      # watch ingestion
docker compose logs -f symmetricds    # watch replication
docker compose build dashboard && docker compose up -d dashboard   # redeploy UI
```

Replication health: check the hub's Grafana "System Overview" → Data Freshness panel.
If data age keeps growing while local ingestion succeeds, SymmetricDS is stalled —
`docker restart symmetricds`.

## Docs

- `docs/ingestion-patterns.md` — ingestion pipeline patterns, file formats
- `docs/sensor-data-model.md` — sensor supertype/subtype design
- `docs/solar-cell-data-model.md` — cell registry, grouping model, example queries
- `docs/improvement-backlog.md` — known gaps and planned improvements
