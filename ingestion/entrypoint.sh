#!/bin/sh
set -e

# Cron does not inherit Docker environment variables — write them to a file that cron sources
printenv | grep -E '^(PG|DATA_ROOT|BATCH_SIZE|DRY_RUN)' \
    | sed 's/^\(.*\)$/export \1/' > /etc/cron_env

# Install daily midnight crontab
echo "0 0 * * * . /etc/cron_env; python /app/ingest.py >> /var/log/ingest.log 2>&1" \
    | crontab -

# Run immediately on container start to catch any backlog without waiting until midnight
python /app/ingest.py

exec cron -f
