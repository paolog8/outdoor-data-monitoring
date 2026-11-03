#!/usr/bin/env bash
# Pull a backup of the measurement PC's database to this machine.
#
#   scripts/backup.sh daily  [--if-reachable]   small: everything except measurement chunk data
#   scripts/backup.sh full   [--if-reachable]   complete database (tens of GB, takes a while)
#
# Read-only on the PC: pg_dump runs inside the postgres container over ssh and streams to
# this machine; nothing is written on the PC. A dump is only kept if the transfer succeeded
# and pg_restore can read it. Each file gets a .sha256.
#
# daily = schema, roles, registry, events, associations, ingestion log, procedures:
#         the data that exists only in the database. Measurements can be rebuilt from the
#         raw exports; the full dump is the fast way back.
#
# Env: BACKUP_HOST (default outdoor-wsl), BACKUP_DIR (default ~/backups/outdoor-data/db),
#      KEEP_DAILY (default 60), KEEP_FULL (default 3)
set -euo pipefail

HOST="${BACKUP_HOST:-outdoor-wsl}"
DEST="${BACKUP_DIR:-$HOME/backups/outdoor-data/db}"
KEEP_DAILY="${KEEP_DAILY:-60}"
KEEP_FULL="${KEEP_FULL:-3}"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=15"
PG_IMAGE="timescale/timescaledb:2.25.2-pg17"   # same version as production, used to verify dumps

mode="${1:-}"
[[ "$mode" == "daily" || "$mode" == "full" ]] || { sed -n '2,16p' "${BASH_SOURCE[0]}"; exit 2; }

mkdir -p "$DEST"
exec 9>"$DEST/.lock"
flock -n 9 || { echo "backup already running" >&2; exit 1; }
log() { echo "$(date -Is) $*" | tee -a "$DEST/backup.log"; }

if [[ "${2:-}" == "--if-reachable" ]] && ! ssh $SSH_OPTS "$HOST" true 2>/dev/null; then
    log "$HOST not reachable, skipping $mode backup"
    exit 0
fi

stamp="$(date +%Y%m%d-%H%M)"
# Runs inside the container, so it uses the container's own credentials. Low priority.
remote_dump() {   # args: pg_dump options
    ssh $SSH_OPTS "$HOST" "docker exec postgres sh -c 'nice -n 19 pg_dump -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" $*'"
}

save() {          # args: final file; reads the dump from stdin
    local file="$1"
    cat > "$file.partial"
    # Keep it only if pg_restore can read the archive.
    if ! docker run --rm -i "$PG_IMAGE" pg_restore --list < "$file.partial" > /dev/null; then
        log "FAILED: $file is not a readable archive, discarding"
        rm -f "$file.partial"
        return 1
    fi
    mv "$file.partial" "$file"
    (cd "$DEST" && sha256sum "$(basename "$file")" > "$(basename "$file").sha256")
    log "OK: $(basename "$file") $(du -h "$file" | cut -f1)"
}

prune() {         # args: glob prefix, number to keep
    local prefix="$1" keep="$2"
    ls -1 "$DEST/$prefix"-*.dump 2>/dev/null | sort | head -n -"$keep" | while read -r f; do
        rm -f "$f" "$f.sha256"; log "pruned $(basename "$f")"
    done
}

start=$SECONDS
case "$mode" in
    daily)
        # Roles (e.g. the replication user) are needed to restore grants.
        ssh $SSH_OPTS "$HOST" "docker exec postgres sh -c 'pg_dumpall -U \"\$POSTGRES_USER\" --globals-only'" \
            > "$DEST/globals-$stamp.sql.partial"
        mv "$DEST/globals-$stamp.sql.partial" "$DEST/globals-$stamp.sql"
        remote_dump "-Fc -Z zstd:3 --exclude-table-data=_timescaledb_internal._hyper_\\*" | save "$DEST/daily-$stamp.dump"
        prune daily "$KEEP_DAILY"
        ls -1 "$DEST"/globals-*.sql 2>/dev/null | sort | head -n -"$KEEP_DAILY" | xargs -r rm -f
        ;;
    full)
        remote_dump "-Fc -Z zstd:3" | save "$DEST/full-$stamp.dump"
        prune full "$KEEP_FULL"
        ;;
esac
log "$mode backup finished in $((SECONDS - start))s"
