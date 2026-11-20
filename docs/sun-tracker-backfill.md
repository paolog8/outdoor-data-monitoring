# Backfilling the sun tracker irradiance data

The M-Box export `mbox_ID_S19057654       .txt` (spaces before `.txt`) sits in every daily
export folder from `data_20250807` on. Until the ingestion learned this name
(`MBOX_FILE_RE` in `ingestion/constants.py`), sensor 24 (`MBox_sun_tracker`) got no rows.
Folders that were already ingested are marked `completed` in `ingestion_log`, so the new
code does not look at them again. This is the procedure to refill them on a database that
has the new code deployed.

Unit: the second column is taken to be mV and is stored as nV integers
(`round(value * 1_000_000)`), like the PT-104 channels.

On the outdoor PC (checked 2026-11-20) the checkout was on `main`, so the fix has to be
merged there before step 2, and the 33 folders are a subset of the 73 completed `data_*`
folders. See `docs/production-data-layout.md`.

## Steps

1. Take a `full` backup first (`docs/backup-restore.md`).
2. Deploy the ingestion image that contains `MBOX_FILE_RE`.
3. List the folders that hold the file and are marked `completed`. Folder names are the
   `data_YYYYMMDD` folders on the data mount:

   ```bash
   ls -d <data mount>/data_*/mbox_ID_S19057654* | xargs -n1 dirname | xargs -n1 basename | sort
   ```

   ```sql
   SELECT folder_name, completed_at, rows_inserted
   FROM ingestion_log
   WHERE status = 'completed' AND folder_name LIKE 'data\_%'
   ORDER BY folder_name;
   ```

4. Delete the `completed` rows of exactly those folders (expected: 33, `data_20250807` to
   `data_20261116`, plus any newer ones that were ingested before the deploy):

   ```sql
   DELETE FROM ingestion_log
   WHERE status = 'completed'
     AND folder_name IN ('data_20250807', ... );   -- the list from step 3
   ```

5. Preview, then run:

   ```bash
   DRY_RUN=true docker compose run --rm ingestion python3 /app/ingest.py
   docker compose run --rm ingestion python3 /app/ingest.py
   ```

   The whole folder is read again, not only the M-Box file. This is safe (every insert is
   `ON CONFLICT ... DO NOTHING`) but takes as long as the first ingestion of those folders.

## Check

```sql
SELECT count(*), min(timestamp), max(timestamp)
FROM irradiance_measurement WHERE irradiance_sensor_id = 24;
```

Expect about 749,000 rows (the row count of the files). On a development copy,
`data_20260908` alone gave 24,070 rows.
