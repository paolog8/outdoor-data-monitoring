import csv
import datetime
import logging
from pathlib import Path

import psycopg2.extras
from constants import IRRADIANCE_FILE_RE, MBOX_FILE_RE, MBOX_RAW_SCALE
from registry import upsert_irradiance_sensor, upsert_mbox_irradiance_sensor
from timeutil import local_to_utc

logger = logging.getLogger(__name__)


def parse_irradiance_file(file_path: Path, raw_scale: int = 1) -> list:
    """
    Parses a TSV file with columns: timestamp, raw_value, irradiance[W/m²].
    The raw value is multiplied by raw_scale and rounded to an integer (the M-Box files
    hold a decimal in mV, see MBOX_RAW_SCALE).
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
                ts = local_to_utc(ts)
                raw_value = int(row[1]) if raw_scale == 1 else round(float(row[1]) * raw_scale)
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


def match_irradiance_file(conn, name: str):
    """Returns (sensor_id, raw_scale) for an irradiance file name, or None for other files."""
    m = IRRADIANCE_FILE_RE.match(name)
    if m:
        return upsert_irradiance_sensor(conn, m.group(1)), 1
    m = MBOX_FILE_RE.match(name)
    if m:
        return upsert_mbox_irradiance_sensor(conn, m.group(1)), MBOX_RAW_SCALE
    return None


def ingest_irradiance_folder(
    conn, folder_path: Path, batch_size: int, dry_run: bool
) -> int:
    """
    Processes all PT-104 and M-Box (sun tracker) irradiance files within a folder.
    One transaction per file.
    """
    total_inserted = 0
    for file_path in sorted(folder_path.iterdir()):
        match = match_irradiance_file(conn, file_path.name)
        if not match:
            continue
        sensor_id, raw_scale = match

        rows = parse_irradiance_file(file_path, raw_scale)
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
