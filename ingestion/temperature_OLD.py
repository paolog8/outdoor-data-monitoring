import datetime
import logging
from pathlib import Path

import psycopg2.extras
import pandas as pd

from constants import TEMP_FILE_OLD_RE
from registry import upsert_temperature_sensor

logger = logging.getLogger(__name__)


def parse_temperature_file(file_path: Path) -> list:
    """
    Parses a CSV file with columns: time, sensorA, sensorB, ...
    Returns list of lists of (datetime, serial, float) tuples.
    """
    rows = []
    with open(file_path, "r") as fh:
        df = pd.read_csv(fh, sep=",", header=0)

        df = df.melt(id_vars=["time"], var_name="serial", value_name="temperature")

        # group the data in df by serial and iterate over each group
        for serial, group in df.groupby("serial"):
            rows_per_sensor = []
            for _, row in group.iterrows():
                try:
                    ts = datetime.datetime.fromisoformat(row["time"])
                    ts = ts.replace(tzinfo=datetime.timezone.utc)
                    temperature = float(row["temperature"])
                    rows_per_sensor.append((ts, serial, temperature))
                except (ValueError, OverflowError) as exc:
                    logger.warning(
                        "Skipping invalid row in %s for sensor %s: %s",
                        file_path,
                        serial,
                        exc,
                    )
            rows.append(rows_per_sensor)
    return rows


def ingest_temperature_measurements(
    cur, sensor_id: int, rows: list, batch_size: int, dry_run: bool
) -> int:
    """Inserts temperature rows in batches. Returns count of rows actually written."""
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        batch_data = [(ts, sensor_id, temperature) for ts, _, temperature in batch]
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
            INSERT INTO temperature_measurement (time, temperature_sensor_id, temperature)
            VALUES %s
            ON CONFLICT (temperature_sensor_id, time) DO NOTHING
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
        m = TEMP_FILE_OLD_RE.match(file_path.name)
        if not m:
            continue
        rows = parse_temperature_file(file_path)
        if not rows:
            logger.info("No valid rows in %s", file_path.name)
            continue
        for rows_per_sensor in rows:
            if not rows_per_sensor:
                continue

            serial = rows_per_sensor[0][1]
            sensor_id = upsert_temperature_sensor(conn, serial)

            try:
                with conn.cursor() as cur:
                    n = ingest_temperature_measurements(
                        cur, sensor_id, rows_per_sensor, batch_size, dry_run
                    )
                conn.commit()
                total_inserted += n
                logger.info(
                    "Committed %d new temperature rows from %s/%s (parsed %d)",
                    n,
                    folder_path.parent.name,
                    file_path.name,
                    len(rows_per_sensor),
                )
            except Exception:
                conn.rollback()
                logger.exception("Failed to ingest %s — rolled back", file_path.name)
                raise

    return total_inserted
