import csv
import datetime
import logging
from pathlib import Path

import psycopg2.extras
from constants import IRRADIANCE_FILE_RE
from registry import upsert_irradiance_sensor

logger = logging.getLogger(__name__)


def parse_irradiance_file(file_path: Path) -> list:
    """
    Parses a TSV file with columns: timestamp, raw_value[uV], irradiance[W/m²].
    Returns list of (datetime, int, float) tuples.
    """
    rows = []
    with open(file_path, "r") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for lineno, row in enumerate(reader, 1):
            if len(row) != 3:
                logger.warning(
                    "Skipping malformed row %d in %s (expected 3 columns, got %d)",
                    lineno,
                    file_path,
                    len(row),
                )
                continue
            try:
                ts = datetime.datetime.fromisoformat(row[0])
                ts = ts.replace(tzinfo=datetime.timezone.utc)
                raw_value = int(row[1])
                irradiance = float(row[2])
                rows.append((ts, raw_value, irradiance))
            except (ValueError, OverflowError) as exc:
                logger.warning(
                    "Skipping invalid row %d in %s: %s", lineno, file_path, exc
                )
    return rows


def ingest_irradiance_measurements(
    cur, sensor_id: int, rows: list, batch_size: int, dry_run: bool
) -> int:
    """Inserts irradiance rows in batches. Returns count of rows actually written."""
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        batch_data = [
            (ts, sensor_id, irradiance, raw_value)
            for ts, raw_value, irradiance in batch
        ]
        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d irradiance rows for sensor %s",
                len(batch_data),
                sensor_id,
            )
            continue
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO irradiance_measurement (timestamp, irradiance_sensor_id, irradiance, raw_value)
            VALUES %s
            ON CONFLICT (irradiance_sensor_id, timestamp) DO NOTHING
            """,
            batch_data,
            page_size=len(batch_data),
        )
        inserted += cur.rowcount
    return inserted


def ingest_irradiance_folder(
    conn, folder_path: Path, batch_size: int, dry_run: bool
) -> int:
    """
    Processes all PT-104 irradiance files within a folder.
    One transaction per file.
    """
    total_inserted = 0
    for file_path in sorted(folder_path.iterdir()):
        m = IRRADIANCE_FILE_RE.match(file_path.name)
        if not m:
            continue
        channel = m.group(1)
        sensor_id = upsert_irradiance_sensor(conn, channel)

        rows = parse_irradiance_file(file_path)
        if not rows:
            logger.info("No valid rows in %s", file_path.name)
            continue

        try:
            with conn.cursor() as cur:
                n = ingest_irradiance_measurements(
                    cur, sensor_id, rows, batch_size, dry_run
                )
            conn.commit()
            total_inserted += n
            logger.info(
                "Committed %d new irradiance rows from %s/%s (parsed %d)",
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
