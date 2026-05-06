import csv
import datetime
import logging
from pathlib import Path

import psycopg2.extras

from constants import BOARDS, CHANNELS, SLOT_CODE_PATTERN

logger = logging.getLogger(__name__)


def parse_file(file_path: Path) -> list:
    """
    Parses a TSV file with columns: timestamp, power, voltage, current.
    Returns list of (datetime, power, voltage, current) tuples.
    """
    rows = []
    with open(file_path, "r") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for lineno, row in enumerate(reader, 1):
            if len(row) != 4:
                logger.warning(
                    "Skipping malformed row %d in %s (expected 4 columns, got %d)",
                    lineno, file_path, len(row),
                )
                continue
            try:
                ts      = datetime.datetime.fromisoformat(row[0])
                ts      = ts.replace(tzinfo=datetime.timezone.utc)
                power   = float(row[1])
                current = float(row[2])
                voltage = float(row[3])
                rows.append((ts, power, current, voltage))
            except (ValueError, OverflowError) as exc:
                logger.warning(
                    "Skipping invalid row %d in %s: %s", lineno, file_path, exc
                )
    return rows


def ingest_file(cur, slot_id, rows: list, batch_size: int, dry_run: bool) -> int:
    """
    Inserts parsed rows in batches. Returns count of rows actually written.
    """
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        batch_data = [
            (ts, slot_id, voltage, current, power)
            for ts, power, current, voltage in batch
        ]
        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d rows for slot %s", len(batch_data), slot_id
            )
            continue
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO mpp_measurement (time, mpp_tracking_slot_id, voltage, current, power)
            VALUES %s
            ON CONFLICT (mpp_tracking_slot_id, time) DO NOTHING
            """,
            batch_data,
            page_size=len(batch_data),
        )
        inserted += cur.rowcount
    return inserted


def ingest_mpp_folder(conn, slot_map: dict, folder_path: Path, batch_size: int, dry_run: bool) -> int:
    """
    Processes all board/channel files within a folder.
    One transaction per file; failed files roll back cleanly.
    """
    total_inserted = 0

    for board in BOARDS:
        for channel in CHANNELS:
            slot_code = SLOT_CODE_PATTERN.format(board, channel)
            slot_id   = slot_map.get(slot_code)
            if slot_id is None:
                logger.warning("No slot found for %s — skipping", slot_code)
                continue

            file_path = folder_path / f"output_board{board}_channel{channel}.txt"
            if not file_path.exists():
                logger.warning("Missing file: %s", file_path)
                continue

            rows = parse_file(file_path)
            if not rows:
                logger.info("No valid rows in %s", file_path.name)
                continue

            try:
                with conn.cursor() as cur:
                    n = ingest_file(cur, slot_id, rows, batch_size, dry_run)
                conn.commit()
                total_inserted += n
                logger.info(
                    "Committed %d new MPP rows from %s/%s (parsed %d)",
                    n, folder_path.parent.name, file_path.name, len(rows),
                )
            except Exception:
                conn.rollback()
                logger.exception("Failed to ingest %s — rolled back", file_path.name)
                raise

    return total_inserted
