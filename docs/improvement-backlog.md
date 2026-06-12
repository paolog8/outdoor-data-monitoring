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

## Open items (this repo — measurement PC)

1. **No backup strategy for the local Postgres.** The hub replica covers replicated
   tables, but local-only state (e.g. `ingestion_log`) and the window before sync are
   unprotected. Add a `pg_dump` cron container or document recovery as
   "re-run ingestion from `data/` exports".
2. **Failed ingestion is silent.** `ingestion_log.status='failed'` rows sit unnoticed.
   Surface them on the dashboard Overview page (count + last error), and/or alert via
   the hub's Grafana once `ingestion_log` is replicated.
3. **No tests for ingestion parsers.** The file-format parsing in `mpp.py`,
   `temperature.py`, `irradiance.py`, `spectral.py` has no test coverage; a regression
   silently corrupts or skips data. A handful of pytest fixtures from real export
   snippets would cover this.
4. **Dashboard has no authentication.** Anyone on the lab network can edit the
   registry. Acceptable on a trusted network, but worth a deliberate decision.
5. **Spectral data not visualized anywhere.** `spectral_measurement` is ingested but
   unused downstream.

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
