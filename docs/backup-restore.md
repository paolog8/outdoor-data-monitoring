# Backup and restore

The measurement PC has no backup of its own. Backups are **pulled** from a second machine
(the developer laptop) over ssh by `scripts/backup.sh`. Nothing is installed or written on the
PC: `pg_dump` runs inside the `postgres` container and streams its output to the laptop.

## What is backed up

| Mode | Contains | Size | Schedule | Kept |
|---|---|---|---|---|
| `daily` | Schema, roles, and every table except the measurement chunk data: registry, connection events, sensor associations, ingestion log, SymmetricDS configuration, functions and procedures | ~2.5 MB | daily, 03:30 | 60 |
| `full` | The whole database (about 66 GB, of which `mpp_measurement` is 63 GB) | tens of GB | Sundays, 22:00 | 3 |

The **daily** dump is the one that matters most: registry, events and associations exist only
in the database. The measurements can be rebuilt from the raw exports (see below), the `full`
dump is the fast way back.

Files live in `~/backups/outdoor-data/db` on the laptop (`BACKUP_DIR`), each with a
`.sha256`. `globals-*.sql` holds the database roles and **contains password hashes**: keep the
directory private. `backup.log` records every run. A dump is kept only if `pg_restore --list`
can read it.

```bash
scripts/backup.sh daily            # now, small
scripts/backup.sh full             # now, large: run it outside measurement hours (about 06:00-17:00)
systemctl --user list-timers 'outdoor-db-backup*'
tail backup.log
```

Take a `full` backup before any risky change to production (migration, bulk delete, re-ingest).

## Restore

Use a server with the same TimescaleDB and PostgreSQL versions as production (see the image
tags in `docker-compose.yml`).

```bash
# 1. empty database with the extension, then switch TimescaleDB into restore mode
psql -U <admin> -c "CREATE DATABASE outdoor_monitoring"
psql -U <admin> -d outdoor_monitoring -c "CREATE EXTENSION timescaledb" -c "SELECT timescaledb_pre_restore()"

# 2. roles first if the original owners are needed (globals-*.sql), then the dump
pg_restore -U <admin> -d outdoor_monitoring --no-owner --no-privileges < full-YYYYMMDD-HHMM.dump

# 3. leave restore mode
psql -U <admin> -d outdoor_monitoring -c "SELECT timescaledb_post_restore()"
```

Use `daily-*.dump` the same way to get everything except the measurements. Then start the
stack; Flyway finds the schema history and applies nothing that is already there.

### Verified
- **Daily dump:** restored into a scratch database and compared with production: all 73
  non-measurement tables had identical row counts, and the object counts matched (215
  functions and procedures, 6 views, 104 triggers, 4 hypertables).
- **Full dump (2026-11-03):** 6.9 GB, pulled in 8 minutes; restored into a scratch database in
  23 minutes (64 GB). Exact row counts per month of `mpp_measurement` (61 months, 619,674,435
  rows), `temperature_measurement` (23,496,173) and `irradiance_measurement` (4,848,348)
  were identical to production, as were the small tables, the object counts and the 683
  chunks. Only the SymmetricDS bookkeeping tables differed slightly, because the replication
  engine keeps writing after the snapshot.

Repeat these checks after any change to the backup script.

## If only the database is lost: rebuild from the exports

The raw export folders (`data/mppt_temp_irr/`) are the source of truth for measurements.
After restoring the `daily` dump, the ingestion service can refill the measurement tables;
ingestion is idempotent. Expect several hours for the full history (about 640 million rows).
Limits:
- Registry, events and associations are **not** in the exports. They come only from the `daily` dump.
- The `ingestion_log` decides what is re-read: clear the entries for folders you want re-ingested.
- Timestamps in the raw files are Europe/Berlin local time; make sure the ingestion code
  being used converts them correctly.
- Data that was never exported (or never ingested) is not recoverable from the exports.

## Known gaps
- The only copy is on the laptop. A second location is still to be chosen.
- The production database contains objects that no migration creates (found by comparing
  `pg_dump --schema-only` of production with a database built from `migrations/`, ignoring the
  SymmetricDS `sym_*` objects). They exist only in the database and in the dumps:
  - procedure `fix_table_timezone(p_table_name, p_time_column)` and table `tz_fix_progress`,
    left from a one-off correction. The procedure deletes and reinserts whole months with
    shifted timestamps; **do not run it again** on data that has already been corrected;
  - functions `experiment_get_cells`, `mpp_measurements_experiment`,
    `mpp_measurements_for_cell_v2`;
  - view `solar_cell_info_view`.

  A database rebuilt only from `migrations/` will lack them. Whether they are still used (for
  example by dashboards on the hub) is to be checked before deciding to add them to the
  migrations or drop them.
