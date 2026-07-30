import csv
import datetime
import logging
from pathlib import Path

import psycopg2.extras
from constants import TEMP_FILE_RE
from registry import upsert_temperature_sensor

logger = logging.getLogger(__name__)


def parse_temperature_file(file_path: Path) -> list:
    """
    Parses a TSV file with columns: timestamp, temperature[°C].
    Returns list of (datetime, float) tuples.
    """
    rows = []
    with open(file_path, "r") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for lineno, row in enumerate(reader, 1):
            if len(row) != 2:
                logger.warning(
                    "Skipping malformed row %d in %s (expected 2 columns, got %d)",
                    lineno,
                    file_path,
                    len(row),
                )
                continue
            try:
                ts = datetime.datetime.fromisoformat(row[0])
                ts = ts.replace(tzinfo=datetime.timezone.utc)
                temperature = float(row[1])
                rows.append((ts, temperature))
            except (ValueError, OverflowError) as exc:
                logger.warning(
                    "Skipping invalid row %d in %s: %s", lineno, file_path, exc
                )
    return rows


def ingest_temperature_measurements(
    cur, sensor_id: int, rows: list, batch_size: int, dry_run: bool
) -> int:
    """Inserts temperature rows in batches. Returns count of rows actually written."""
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        batch_data = [(ts, sensor_id, temperature) for ts, temperature in batch]
        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d temperature rows for sensor %s",
                len(batch_data),
                sensor_id,
            )
            continue
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO temperature_measurement (timestamp, temperature_sensor_id, temperature)
            VALUES %s
            ON CONFLICT (temperature_sensor_id, timestamp) DO NOTHING
            """,
            batch_data,
            page_size=len(batch_data),
        )
        inserted += cur.rowcount
    return inserted


def ingest_temperature_folder(
    conn, folder_path: Path, batch_size: int, dry_run: bool
) -> int:
    """
    Processes all m7004 temperature files within a folder.
    One transaction per file.
    """
    total_inserted = 0
    for file_path in sorted(folder_path.iterdir()):
        m = TEMP_FILE_RE.match(file_path.name)
        if not m:
            continue
        serial = m.group(1)
        sensor_id = upsert_temperature_sensor(conn, serial)

        rows = parse_temperature_file(file_path)
        if not rows:
            logger.info("No valid rows in %s", file_path.name)
            continue

        try:
            with conn.cursor() as cur:
                n = ingest_temperature_measurements(
                    cur, sensor_id, rows, batch_size, dry_run
                )
            conn.commit()
            total_inserted += n
            logger.info(
                "Committed %d new temperature rows from %s/%s (parsed %d)",
                n,
                folder_path.parent.name,
                file_path.name,
                len(rows),
            )
        except Exception:
            conn.rollback()
            logger.exception("Failed to ingest %s — rolled back", file_path.name)
            raise

    return total_inserted
