# Improvement Backlog

Identified 2026-06-12 during a full review of both repos. The previous backlog
(`dashboard-improvements.md`, items 1–5) was fully implemented on
`feature/dashboard-improvements` and has been removed.

## Done in the 2026-06-12 review

- Hub: replaced the scientifically meaningless "Total Power" Grafana panels with
  **Data Freshness** and **Power per Cell** (System Overview).
- Hub: added **Environmental Conditions** and **Connection History & Data Coverage**
  dashboards (completing the dashboard roadmap).
- Hub: documented all dashboards, the PCE formula, and query performance rules in
  `grafana/dashboards/README.md`; rewrote the stale hub README.
- This repo: proper README, this backlog, gitignored `docker-compose.override.yml`.

## Done in the second pass (2026-06-12, branch `feature/registry-and-ops`)

- **Event correction**: Corrections tab on the Events page. Only the most recent event
  per slot is deletable (enforced in SQL) so historical measurement attribution can
  never silently change; explicit confirmation required.
- **CSV cell import**: Registry → Cells → "Import cells from CSV". All-or-nothing with
  per-row validation; resolves owner/manufacturer/group/cell_type/experiment by name.
- **Grafana deep-links**: cell edit form links to the hub's Single Cell Deep-Dive
  (`GRAFANA_BASE_URL` env var, wired through docker-compose; set it in `.env`).
- **CI**: Python syntax check + migration numbering validation (GitHub Actions).
- **Pinned flyway image** to `11-alpine` (was `:latest`).
- Hub side (branch `feature/system-overview-rework`): connection-event annotations on
  Deep-Dive/Degradation, experiment filter on Multi-Cell Comparison, Daily Energy Yield
  panel, Ingestion Runs panel (replicated `ingestion_log`), CI for dashboards/migrations.

## Open items (this repo — measurement PC)

1. **No backup strategy for the local Postgres.** The hub replica covers replicated
   tables, but local-only state and the window before sync are unprotected. Add a
   `pg_dump` cron container or document recovery as "re-run ingestion from `data/`
   exports".
2. **No tests for ingestion parsers.** The file-format parsing in `mpp.py`,
   `temperature.py`, `irradiance.py`, `spectral.py` has no test coverage; a regression
   silently corrupts or skips data. A handful of pytest fixtures from real export
   snippets would cover this. (CI scaffold now exists to run them.)
3. **Dashboard has no authentication.** Anyone on the lab network can edit the
   registry. Acceptable on a trusted network, but worth a deliberate decision.
4. **Spectral data not visualized anywhere.** `spectral_measurement` is ingested but
   unused downstream.
5. **Corrections tab covers MPP events only** — sensor_association_event corrections
   would follow the same latest-per-(sensor,cell) pattern.
6. **Per-cell irradiance for PCE** (cross-repo, the big one). PCE currently uses the
   global irradiance sensor. Spec: new helper `irradiance_for_cell(cell_name, start,
   end, bucket)` mirroring `mpp_measurements_for_cell`'s LEAD-interval logic over
   `sensor_association_event` (irradiance sensors only), falling back to the global
   average when the cell has no associated sensor. Migration here (next: V32) + hub
   copy (+3 offset → V35), then switch the PCE queries in all hub dashboards. Needs
   the migration applied before the dashboard change is deployed.

## Open items (hub repo — see also `grafana/dashboards/README.md` ideas)

1. **Grafana alerting on Data Freshness** (email/notification when MPP data age exceeds
   the export cadence) — highest operational value, low effort.
2. **`src/api` FastAPI routes return mock data** — either back them with the DB or
   remove them to avoid misleading users.
3. **Legacy `perocube` Streamlit UI / notebooks**: decide deprecation or maintenance;
   they target the legacy schema and confuse new contributors.
4. **Dead migrations** `V26`/`V27` in `db/outdoor_migrations/` — harmless but could be
   cleaned up with a follow-up migration dropping the uncallable functions (low
   priority; coordinate with frozen Flyway history).
