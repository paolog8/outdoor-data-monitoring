#!/bin/sh
set -e

# Cron does not inherit Docker environment variables — write them to a file that cron sources
printenv | grep -E '^(PG|DATA_ROOT|BATCH_SIZE|DRY_RUN)' \
    | sed 's/^\(.*\)$/export \1/' > /etc/cron_env

# Install daily midnight crontab.
# cron runs jobs with its own minimal PATH (doesn't include /usr/local/bin, where
# python3 lives in this image), so call it by absolute path rather than relying on
# /etc/cron_env to carry PATH too.
echo "0 2 * * * . /etc/cron_env; /usr/local/bin/python3 /app/ingest.py >> /var/log/ingest.log 2>&1" \
    | crontab -

# Run immediately on container start to catch any backlog without waiting until midnight
python3 /app/ingest.py || true

exec cron -f
