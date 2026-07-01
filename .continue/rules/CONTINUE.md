# Outdoor PV Monitoring System

This project is an **outdoor photovoltaic (PV) measurement and monitoring system** deployed at PVcomB. It captures MPP-tracker, temperature, irradiance, and spectral data from measurement hardware, stores it in a PostgreSQL + TimescaleDB database, and provides a Streamlit dashboard for managing the cell registry and operational events.

## Overview

### Purpose

This system tracks outdoor performance measurements of photovoltaic devices (primarily perovskite cells and tandems) under real-world conditions. It maintains a comprehensive registry of cells, groups, scientists, experiments, and sensors, while recording detailed connection/disconnection events and sensor associations over time.

### Key Technologies

- **Database**: PostgreSQL 17 with TimescaleDB extension for time-series data
- **Streamlit App**: Web-based UI for data entry and registration (port 8501)
- **Ingestion Pipeline**: Automated daily ingestion of measurement data exports
- **SymmetricDS**: Real-time data replication to central hub for analysis
- **Docker Compose**: Containerized deployment of all services

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Outdoor Measurement PC                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────┐  ┌──────────────┐  ┌─────────────────┐  ┌───────────┐ │
│  │  Data Exports   │  │  Ingestion   │  │  Streamlit      │  │ Symmetric │ │
│  │  (text files)   ├──►│  (cron)      │  │  Dashboard      │  │   Edge    │ │
│  └─────────────────┘  └──────────────┘  └─────────────────┘  └───────────┘ │
│                            │                  │                  │           │
│                            ▼                  ▼                  ▼           │
│                    ┌───────────────────────────────────────┐                │
│                    │       PostgreSQL + TimescaleDB        │                │
│                    │     (outdoor_monitoring database)     │                │
│                    └───────────────────────────────────────┘                │
│                              │                                              │
│                              ▼                                              │
│                    ┌───────────────────────┐                                │
│                    │     Central Hub       │                                │
│                    │    (Grafana analysis) │                                │
│                    └───────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Getting Started

### Prerequisites

- Docker and Docker Compose installed
- Git access to clone the repository

### Installation

1. Clone the repository

2. Create a `.env` file in the project root (never commit this):
   ```env
   POSTGRES_DB=outdoor_monitoring
   POSTGRES_USER=postgres
   POSTGRES_PASSWORD=your_secure_password
   SYM_PASSWORD=your_symmetricds_password
   SYM_SERVER_ADDRESS=hub-hostname
   SYM_SERVER_PORT=31416
   GRAFANA_BASE_URL=https://hub-hostname/grafana
   ```

3. Start all services:
   ```bash
   docker compose up -d
   ```

### Running the Dashboard

**Via Docker (production-like):**
```bash
docker compose up dashboard
# Dashboard available at http://localhost:8501
```

**Locally (development):**
```bash
cd dashboard
pip install -r requirements.txt
PGHOST=localhost PGPORT=5432 PGDATABASE=outdoor_monitoring PGUSER=postgres PGPASSWORD=your_password streamlit run app.py
```

### Basic Usage

1. **Register entities** in the Registry tab:
   - Scientists/Researchers
   - Solar cells (individual or batch)
   - Cell groups (substrates, tandems, batches)
   - Experiments and Projects
   - Sensors (temperature, irradiance, spectral)

2. **Record connection events** in the Events tab:
   - Connect cells to MPP tracker slots with connection mode and polarity
   - Associate sensors with cells
   - Record disconnection and dissociation events when done

3. **Access data** via:
   - Streamlit dashboard (local registry + events)
   - Grafana dashboards on the central hub (visualization/analysis)

### Running Tests

This is primarily an operational system without formal unit tests. To verify:

```bash
# Test ingestion works
docker compose logs -f ingestion

# Verify database connectivity
docker compose exec postgres psql -U postgres -d outdoor_monitoring -c "SELECT 1"

# Check SymmetricDS replication
docker compose logs -f symmetricds
```

## Project Structure

```
├── dashboard/                  # Streamlit web application
│   ├── app.py                  # Main entry point, page navigation
│   ├── db.py                   # Database access layer (psycopg2)
│   ├── requirements.txt        # Python dependencies (streamlit, psycopg2)
│   ├── Dockerfile              # Dashboard container definition
│   └── pages/
│       ├── overview.py         # Home page: metrics, slot occupancy
│       ├── 1_Events.py         # Connection/disconnection events
│       └── 2_Registry.py       # CRUD for scientists, cells, groups, etc.
├── ingestion/                  # Automated data ingestion pipeline
│   ├── ingest.py               # Main entry point, folder discovery
│   ├── mpp.py                  # MPP tracker data parsing/insertion
│   ├── temperature.py          # Temperature sensor ingestion
│   ├── irradiance.py           # Irradiance sensor ingestion
│   ├── spectral.py             # Spectral sensor ingestion
│   ├── registry.py             # Sensor upsert helpers
│   ├── constants.py            # Shared regexes and constants
│   ├── db.py                   # Database connection for ingestion
│   └── Dockerfile              # Ingestion container definition
├── migrations/                 # Flyway database migrations
│   ├── V1__baseline.sql
│   ├── V2__create_mpp_tracker.sql
│   ├── V3__create_mpp_tracking_slot.sql
│   ├── ...                     # V4–V31 for schema evolution
│   └── V31__drop_legacy_mpp_measurements_for_cell.sql
├── symmetricds/                # SymmetricDS edge node configuration
│   └── engines/                # Engine configuration files
├── data/                       # Measurement data exports (ignored)
├── docs/                       # Documentation
│   ├── ingestion-patterns.md   # Ingestion pipeline details
│   ├── solar-cell-data-model.md # Cell/Group registry schema
│   ├── sensor-data-model.md    # Sensor hierarchy design
│   └── improvement-backlog.md  # Known gaps and planned work
├── docker-compose.yml          # Service definitions
├── docker-compose.override.yml # Local development overrides (gitignored)
├── .env                        # Environment variables (gitignored)
├── README.md                   # Project overview
└── .continue/rules/CONTINUE.md # This file
```

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `dashboard/` | Streamlit web application for UI |
| `ingestion/` | Automated data ingestion from file exports |
| `migrations/` | Database schema migrations (Flyway versioned) |
| `symmetricds/` | Replication configuration to central hub |
| `data/` | Raw measurement data exports (not committed) |
| `docs/` | Additional documentation files |

### Key Configuration Files

- **`.env`**: Environment variables for database credentials, replication settings (never commit)
- **`docker-compose.yml`**: Service definitions, volume mounts, dependencies
- **`dashboard/requirements.txt`**: Python dependencies for the web app
- **`ingestion/requirements.txt`**: Python dependencies for ingestion

## Development Workflow

### Coding Standards

- **Python**: Follow PEP 8 style guide
- **Database**: Use explicit SQL queries via psycopg2 (no ORM)
- **Streamlit**: Use session state for form management, `@st.cache_data(ttl=30)` for reads
- **Migrations**: Flyway-style versioned SQL files with incremental changes

### Testing Approach

- **Manual testing** via the Streamlit dashboard is primary
- **Ingestion verification**: Check `ingestion_log` table for successful completion
- **Database integrity**: Verify foreign key constraints and unique indexes
- **Replication health**: Monitor data freshness on the central hub's Grafana

### Build and Deployment

```bash
# Start all services
docker compose up -d

# Build/rebuild specific services
docker compose build dashboard
docker compose build ingestion

# View logs
docker compose logs -f dashboard
docker compose logs -f ingestion
docker compose logs -f symmetricds

# Stop services
docker compose down
```

### Contribution Guidelines

1. **Database changes**:
   - Add migration file in `migrations/V{N}__description.sql`
   - Update documentation in `docs/` as needed
   - Run locally to verify: `docker compose up -d flyway postgres`

2. **UI changes**:
   - Test with sample data via `docker compose up dashboard`
   - Update `dashboard/CLAUDE.md` if architecture patterns change

3. **Ingestion changes**:
   - Follow patterns in `docs/ingestion-patterns.md` for adding new sensor types
   - Test with dry run: `DRY_RUN=true docker compose run --rm ingestion`

## Key Concepts

### Domain Terminology

| Term | Meaning |
|------|---------|
| **Solar Cell** | Individual photovoltaic device under test (e.g., SUB003_px_A) |
| **Cell Group** | Physical/Logical grouping (substrate, tandem, module, batch) |
| **MPP Tracker** | Maximum Power Point tracking measurement device |
| **Slot** | Connection point on an MPP tracker (board_N_channel_M format) |
| **Connection Event** | Record of connecting/disconnecting a cell to a tracker slot |
| **Sensor Association** | Linking a sensor (temp/irr/spectral) to a cell for measurement context |
| **Experiment** | Scientific study involving multiple cells under controlled conditions |
| **Project** | High-level research initiative containing one or more experiments |

### Core Abstractions

**Event-Log Pattern**: Instead of storing current state directly, the system records all state changes as immutable events. Current state is derived by finding the most recent event for each entity. This provides full auditability and enables replaying history.

**Sensor Supertype/Subtype**: All sensors inherit from a `sensor` parent table, with specific types (temperature, irradiance, spectral) in separate subtype tables. This allows unified queries while preserving type-specific properties.

**Hypertable for Time-Series**: TimescaleDB's hypertable partitioning automatically handles time-based data distribution, enabling efficient queries over large time ranges.

### Design Patterns

- **Append-Only Event Log**: All temporal relationships (cell connections, sensor associations) are recorded as immutable events
- **Event-Driven State Derivation**: Current state is always computed from the latest event, not stored separately
- **Batch Operations**: UI supports batch entry via base name + comma-separated suffixes
- **Idempotent Ingestion**: Data ingestion uses UNIQUE constraints with `ON CONFLICT DO NOTHING` for safe re-runs

## Common Tasks

### Registering a New Cell

**Via Dashboard** (Registry → Cells → Register new cells):
1. Enter base name and optional suffixes (e.g., `SUB003_px` + `A,B,C` for a batch)
2. Fill in metadata (area, initial PCE, structure, type)
3. Assign to group/experiment if applicable
4. Click "Register batch"

**Direct SQL**:
```sql
INSERT INTO solar_cell (name, area_cm2, initial_pce, structure, cell_type_id, owner_id, manufacturer_id)
VALUES ('CELL-001', 0.16, 18.5, 'ITO/NiOx/Pero/C60/BCP/Ag', 1, owner_id, mfr_id)
RETURNING id;
```

### Connecting a Cell to a Tracker Slot

**Via Dashboard** (Events → Connect & Associate):
1. Enter cell name(s) in Setup tab
2. Select tracker and slot (or use board/channel grid)
3. Choose connection mode (MPP tracking, short circuit, open circuit)
4. Select associated sensors
5. Click "Submit setup events"

**Direct SQL**:
```sql
INSERT INTO mpp_connection_event (event_type, mode_id, polarity_id, occurred_at, solar_cell_id, mpp_tracking_slot_id)
VALUES ('connection', mode_id, polarity_id, NOW(), cell_id, slot_id);
```

### Adding a New Migration

1. Create migration file: `migrations/V{N}__<description>.sql`
2. Apply migration: `docker compose up flyway`
3. Test locally: `docker compose up -d`
4. Update documentation as needed

**Important**: Never renumber existing migrations. The central hub repository keeps a copy with version numbers offset by +3.

### Viewing Measurements for a Cell

```sql
-- All measurements for a specific cell
SELECT * FROM mpp_measurements_for_cell('CELL-001');

-- With time range
SELECT * FROM mpp_measurements_for_cell('CELL-001', '2024-06-01', '2024-07-01');

-- Downsampled (1-hour buckets)
SELECT * FROM mpp_measurements_for_cell('CELL-001', '2024-06-01', '2024-07-01', '1 hour');
```

### Re-ingesting Data

```bash
# Find failed ingestion entries
docker compose exec postgres psql -U postgres -d outdoor_monitoring -c \
  "SELECT * FROM ingestion_log WHERE status = 'failed' ORDER BY started_at DESC;"

# Remove or update the failed row
docker compose exec postgres psql -U postgres -d outdoor_monitoring -c \
  "DELETE FROM ingestion_log WHERE id = <failed_id>;"

# Wait for next cron run or force immediate ingestion
docker compose run --rm ingestion python /app/ingest.py
```

## Troubleshooting

### Common Issues

**Dashboard won't start**:
- Check `.env` file exists with valid credentials
- Verify database is healthy: `docker compose exec postgres pg_isready`
- Check container logs: `docker compose logs dashboard`

**Ingestion failing**:
- Verify data files are in correct format (see `docs/ingestion-patterns.md`)
- Check `ingestion_log` for error messages
- Test with dry run: `DRY_RUN=true docker compose run --rm ingestion`

**Replication not working**:
- Verify SymmetricDS logs: `docker compose logs symmetricds`
- Check SymmetricDS configuration in `symmetricds/engines/`
- Ensure hub connectivity from `.env` is correct
- Check hub's Grafana "System Overview" → Data Freshness panel

**Database connection refused**:
- Verify PostgreSQL is healthy: `docker compose ps`
- Check container logs: `docker compose logs postgres`
- Ensure `.env` credentials match `docker-compose.yml` configuration

**Migration failing**:
- Check Flyway logs: `docker compose logs flyway`
- Verify migration SQL syntax
- Ensure migrations are applied in order (V1 before V2, etc.)

### Debugging Tips

**View all active connections**:
```sql
SELECT * FROM mpp_tracker_status('tracker_name');
```

**Check sensor associations for a cell**:
```sql
SELECT * FROM sensor_association_event
WHERE solar_cell_id = (SELECT id FROM solar_cell WHERE name = 'CELL-001')
ORDER BY occurred_at DESC;
```

**List all schema objects**:
```sql
SELECT table_name, table_type FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;
```

**Inspect connection state changes**:
```sql
SELECT * FROM mpp_connection_event
WHERE solar_cell_id = (SELECT id FROM solar_cell WHERE name = 'CELL-001')
ORDER BY occurred_at DESC;
```

## References

### Documentation

- **README.md**: Project overview and quick start
- **dashboard/CLAUDE.md**: Dashboard architecture details
- **docs/ingestion-patterns.md**: Data ingestion pipeline patterns
- **docs/solar-cell-data-model.md**: Cell and group registry schema
- **docs/sensor-data-model.md**: Sensor hierarchy design
- **docs/improvement-backlog.md**: Known gaps and planned improvements

### Database Schema

Key tables:
- `solar_cell` — Individual PV devices registry
- `solar_cell_group` — Groupings (substrates, tandems, batches)
- `mpp_tracker` — MPP tracking devices
- `mpp_tracking_slot` — Connection points on trackers
- `mpp_connection_event` — Cell connection/disconnection history
- `sensor` (supertype) + subtypes (temperature, irradiance, spectral)
- `sensor_association_event` — Sensor-cell association history
- `ingestion_log` — Ingestion pipeline tracking

### Key Views & Functions

- `mpp_tracker_status(tracker_name)` — Current slot occupancy
- `mpp_measurements_for_cell(cell_name, start, end, bucket_interval)` — Measurements with time filtering and downsampling
- `cell_experiments(cell_name)` — Experiments a cell belongs to

### External Resources

- [Streamlit Documentation](https://docs.streamlit.io/)
- [TimescaleDB Documentation](https://docs.timescale.com/)
- [SymmetricDS Documentation](https://www.symmetricds.org/doc)
- [Flyway Documentation](https://flywaydb.org/documentation/)

## Notes for AI Assistants

This is an operational system with strict data integrity requirements:

1. **Database changes require migrations** — never modify schema directly
2. **Event log is append-only** — current state is derived, not stored separately
3. **Replication is critical** — changes must work with SymmetricDS to the hub
4. **Test changes locally** — use Docker for development before deploying
5. **Never commit `.env`** — it contains sensitive credentials
6. **Follow existing patterns** — especially in `db.py` and page modules

When adding features:
- Start with database migration if schema changes
- Update `db.py` with new query functions
- Modify UI pages as needed
- Update documentation in `docs/` and `README.md`
- Test end-to-end before committing