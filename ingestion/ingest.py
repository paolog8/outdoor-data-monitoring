"""
MPP data ingestion pipeline for the PeroCube outdoor monitoring system.

Scans DATA_ROOT for new export folders (data_YYYYMMDD/), ingests each
output_boardN_channelN.txt file into the mpp_measurement hypertable, and
records progress in ingestion_log for idempotent re-runs.
"""

import csv
import datetime
import logging
import os
import re
import sys
import uuid
from pathlib import Path

import psycopg2
import psycopg2.extras

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRACKER_NAME      = "PeroCube"
TRACKER_MODEL     = "PeroCube"
SLOT_CODE_PATTERN = "PC01_board{:02d}_channel{:02d}"
BOARDS            = range(1, 11)   # boards 1..10 (board 1 may or may not exist)
CHANNELS          = range(1, 25)   # channels 1..24
DEFAULT_BATCH_SIZE = 1000
FOLDER_RE         = re.compile(r"^data_\d{8}$")

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------

def get_connection():
    required = ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")

    conn = psycopg2.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ["PGPORT"]),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )
    conn.autocommit = False
    return conn


# ---------------------------------------------------------------------------
# Registry bootstrap
# ---------------------------------------------------------------------------

def ensure_registry(conn) -> uuid.UUID:
    """Idempotently create the PeroCube tracker and all 240 slots. Returns tracker UUID."""
    with conn.cursor() as cur:
        # Upsert tracker
        cur.execute(
            """
            INSERT INTO mpp_tracker (name, model)
            VALUES (%s, %s)
            ON CONFLICT ON CONSTRAINT uq_mpp_tracker_name_model DO NOTHING
            """,
            (TRACKER_NAME, TRACKER_MODEL),
        )
        cur.execute(
            "SELECT id FROM mpp_tracker WHERE name = %s AND model = %s",
            (TRACKER_NAME, TRACKER_MODEL),
        )
        tracker_id = cur.fetchone()[0]

        # Upsert all slots in one round trip
        slot_rows = [
            (SLOT_CODE_PATTERN.format(board, channel), tracker_id)
            for board in BOARDS
            for channel in CHANNELS
        ]
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO mpp_tracking_slot (slot_code, mpp_tracker_id)
            VALUES %s
            ON CONFLICT ON CONSTRAINT uq_mpp_tracking_slot_tracker_code DO NOTHING
            """,
            slot_rows,
        )

    conn.commit()
    logger.info(
        "Registry ready: tracker=%s, slots=%d defined", tracker_id, len(slot_rows)
    )
    return tracker_id


# ---------------------------------------------------------------------------
# Slot map (fetch once, reuse for all files)
# ---------------------------------------------------------------------------

def build_slot_map(conn, tracker_id) -> dict:
    """Returns {slot_code: uuid} for every slot belonging to this tracker."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_code, id FROM mpp_tracking_slot WHERE mpp_tracker_id = %s",
            (tracker_id,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Folder discovery
# ---------------------------------------------------------------------------

def discover_pending_folders(conn, data_root: Path) -> list:
    """Returns folder names not yet 'completed', sorted oldest-first."""
    all_folders = sorted(
        d.name
        for d in data_root.iterdir()
        if d.is_dir() and FOLDER_RE.match(d.name)
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT folder_name FROM ingestion_log WHERE status = 'completed'"
        )
        completed = {row[0] for row in cur.fetchall()}

    pending = [f for f in all_folders if f not in completed]
    return pending


# ---------------------------------------------------------------------------
# File parsing
# ---------------------------------------------------------------------------

def parse_file(file_path: Path) -> list:
    """
    Parses a TSV file with columns: timestamp, power, voltage, current.
    Returns list of (datetime, power, voltage, current) tuples.
    Malformed rows are skipped with a WARNING log.
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
                voltage = float(row[2])
                current = float(row[3])
                rows.append((ts, power, voltage, current))
            except (ValueError, OverflowError) as exc:
                logger.warning(
                    "Skipping invalid row %d in %s: %s", lineno, file_path, exc
                )
    return rows


# ---------------------------------------------------------------------------
# File ingestion
# ---------------------------------------------------------------------------

def ingest_file(cur, slot_id, rows: list, batch_size: int, dry_run: bool) -> int:
    """
    Inserts parsed rows in batches. Returns count of rows actually written
    (ON CONFLICT DO NOTHING means duplicates are not counted).
    """
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        # File column order: power, voltage, current → map to DB column order
        batch_data = [
            (ts, slot_id, voltage, current, power)
            for ts, power, voltage, current in batch
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
        )
        inserted += cur.rowcount
    return inserted


# ---------------------------------------------------------------------------
# Folder ingestion
# ---------------------------------------------------------------------------

def ingest_folder(conn, slot_map: dict, folder_path: Path, batch_size: int, dry_run: bool) -> int:
    """
    Processes all board/channel files within a folder.
    One transaction per file: failed files roll back cleanly; committed files
    are preserved on retry via ON CONFLICT DO NOTHING.
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
                    "Committed %d new rows from %s (parsed %d)",
                    n, file_path.name, len(rows),
                )
            except Exception:
                conn.rollback()
                logger.exception("Failed to ingest %s — rolled back", file_path.name)
                raise

    return total_inserted


# ---------------------------------------------------------------------------
# Folder lifecycle (ingestion_log)
# ---------------------------------------------------------------------------

def process_folder(conn, slot_map: dict, folder_name: str, data_root: Path, batch_size: int, dry_run: bool):
    """Wraps folder ingestion with ingestion_log lifecycle management."""
    log_id = None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_log (folder_name, status) VALUES (%s, 'started') RETURNING id",
            (folder_name,),
        )
        log_id = cur.fetchone()[0]
    conn.commit()  # Persist 'started' immediately so crashes leave an audit trail

    folder_path = data_root / folder_name / "data"
    if not folder_path.is_dir():
        msg = f"Data subdirectory not found: {folder_path}"
        logger.error(msg)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_log SET status='failed', completed_at=now(), error_message=%s WHERE id=%s",
                (msg, log_id),
            )
        conn.commit()
        return

    try:
        n = ingest_folder(conn, slot_map, folder_path, batch_size, dry_run)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_log
                SET status='completed', completed_at=now(), rows_inserted=%s
                WHERE id=%s
                """,
                (n, log_id),
            )
        conn.commit()
        logger.info("Folder %s completed: %d new rows inserted", folder_name, n)
    except Exception as exc:
        conn.rollback()
        error_msg = str(exc)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_log
                SET status='failed', completed_at=now(), error_message=%s
                WHERE id=%s
                """,
                (error_msg, log_id),
            )
        conn.commit()
        logger.error("Folder %s failed: %s", folder_name, error_msg)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )

    dry_run    = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
    batch_size = int(os.environ.get("BATCH_SIZE", DEFAULT_BATCH_SIZE))
    data_root  = Path(os.environ.get("DATA_ROOT", "/data"))

    if dry_run:
        logger.info("DRY RUN mode — no data will be written to the database")

    if not data_root.is_dir():
        logger.error("DATA_ROOT does not exist or is not a directory: %s", data_root)
        sys.exit(1)

    conn = get_connection()
    try:
        tracker_id = ensure_registry(conn)
        slot_map   = build_slot_map(conn, tracker_id)
        pending    = discover_pending_folders(conn, data_root)

        if not pending:
            logger.info("No pending folders found. Exiting.")
            return

        logger.info("%d pending folder(s): %s", len(pending), pending)
        for folder_name in pending:
            process_folder(conn, slot_map, folder_name, data_root, batch_size, dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
