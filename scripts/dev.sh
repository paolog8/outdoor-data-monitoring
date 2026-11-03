#!/usr/bin/env bash
# Helper for the local dev stack (docker-compose.dev.yml). Runs only on this machine.
#
#   scripts/dev.sh up              start database, migrations and dashboard (http://localhost:8502)
#   scripts/dev.sh migrate         apply new migrations/V*.sql to the running dev database
#   scripts/dev.sh seed [export...] pick the export folders to ingest, e.g. data_20240222
#                                  (each folder holds everything recorded since the previous
#                                  export; the date is the day of the export). Default: two.
#   scripts/dev.sh ingest          run ingestion once over ./dev-data
#   scripts/dev.sh psql            open psql in the dev database
#   scripts/dev.sh grafana         also start Grafana (http://localhost:3001)
#   scripts/dev.sh logs [service]  follow logs
#   scripts/dev.sh down            stop (keeps data)
#   scripts/dev.sh reset           stop and delete the dev database
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

dc() { docker compose --env-file .env.dev -f docker-compose.yml -f docker-compose.dev.yml "$@"; }

# Hard-link the top-level migrations/V*.sql into ./dev-migrations (what flyway mounts).
refresh_migrations() {
    mkdir -p dev-migrations
    rm -f dev-migrations/*.sql
    cp -l migrations/V*.sql dev-migrations/
}

cmd="${1:-help}"
shift || true

case "$cmd" in
    up)      refresh_migrations; dc up -d --build postgres flyway dashboard ;;
    migrate) refresh_migrations; dc run --rm flyway migrate ;;
    down)    dc down ;;
    reset)   dc down -v ;;
    grafana) dc --profile grafana up -d grafana ;;
    logs)    dc logs -f "$@" ;;
    psql)    dc exec postgres psql -U dev -d outdoor_dev "$@" ;;
    ingest)  dc --profile ingest run --rm --build --entrypoint python3 ingestion /app/ingest.py ;;
    seed)
        # Hard links: no extra disk space, and the source files stay untouched.
        exports=("$@")
        [[ ${#exports[@]} -eq 0 ]] && exports=(data_20240222 data_20251126)
        mkdir -p dev-data/mppt_temp_irr
        for d in "${exports[@]}"; do
            src="data/mppt_temp_irr/$d"
            [[ -d "$src" ]] || { echo "not found: $src" >&2; exit 1; }
            [[ -e "dev-data/mppt_temp_irr/$d" ]] || cp -al "$src" "dev-data/mppt_temp_irr/$d"
            echo "seeded $d"
        done
        ;;
    *)       sed -n '2,15p' "${BASH_SOURCE[0]}" ;;
esac
