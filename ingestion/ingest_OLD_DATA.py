"""
MPP data ingestion pipeline for the PeroCube outdoor monitoring system.

Scans DATA_ROOT for new export folders (data_YYYYMMDD/), ingests each
output_boardN_channelN.txt file into the mpp_measurement hypertable, and
records progress in ingestion_log for idempotent re-runs.
"""

import logging
import os
import sys
from pathlib import Path

from constants import DEFAULT_BATCH_SIZE, FOLDER_RE_OLD
from db import get_connection
from mpp import ingest_mpp_folder
from registry import build_slot_map, ensure_registry
from spectral import discover_pending_spectral_files, ingest_spectral_file
from temperature_OLD import ingest_temperature_folder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Folder discovery
# ---------------------------------------------------------------------------


def discover_pending_folders(conn, data_root: Path) -> list:
    """Returns folder names not yet 'completed', sorted oldest-first."""
    all_folders = sorted(
        d.name
        for d in data_root.iterdir()
        if d.is_dir() and FOLDER_RE_OLD.match(d.name)
    )
    with conn.cursor() as cur:
        cur.execute("SELECT folder_name FROM ingestion_log WHERE status = 'completed'")
        completed = {row[0] for row in cur.fetchall()}

    return [f for f in all_folders if f not in completed]


# ---------------------------------------------------------------------------
# Folder lifecycle (ingestion_log)
# ---------------------------------------------------------------------------


def process_folder(
    conn,
    slot_map: dict,
    folder_name: str,
    data_root: Path,
    batch_size: int,
    dry_run: bool,
):
    """Wraps folder ingestion with ingestion_log lifecycle management."""
    log_id = None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_log (folder_name, status) VALUES (%s, 'started') RETURNING id",
            (folder_name,),
        )
        log_id = cur.fetchone()[0]
    conn.commit()

    folder_path = data_root / folder_name
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
        n = ingest_mpp_folder(conn, slot_map, folder_path, batch_size, dry_run)
        n += ingest_temperature_folder(conn, folder_path, batch_size, dry_run)
        #       n += ingest_irradiance_folder(conn, folder_path, batch_size, dry_run)
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

    dry_run = os.environ.get("DRY_RUN", "false").strip().lower() == "true"
    batch_size = int(os.environ.get("BATCH_SIZE", DEFAULT_BATCH_SIZE))
    data_root = Path(os.environ.get("DATA_ROOT", "/data"))

    if dry_run:
        logger.info("DRY RUN mode — no data will be written to the database")

    if not data_root.is_dir():
        logger.error("DATA_ROOT does not exist or is not a directory: %s", data_root)
        sys.exit(1)

    conn = get_connection()
    try:
        tracker_id = ensure_registry(conn)
        slot_map = build_slot_map(conn, tracker_id)
        mppt_root = data_root / "mppt_temp_irr"
        pending = discover_pending_folders(conn, mppt_root)

        if pending:
            logger.info("%d pending folder(s): %s", len(pending), pending)
            for folder_name in pending:
                process_folder(
                    conn, slot_map, folder_name, mppt_root, batch_size, dry_run
                )
        else:
            logger.info("No pending folders found.")

        spectral_root = data_root / "spectral_data"
        if spectral_root.is_dir():
            pending_spectral = discover_pending_spectral_files(conn, spectral_root)
            if pending_spectral:
                logger.info(
                    "%d pending spectral file(s): %s",
                    len(pending_spectral),
                    [str(p) for p in pending_spectral],
                )
                for csv_path in pending_spectral:
                    log_key = f"spectral:{csv_path.relative_to(spectral_root)}"
                    ingest_spectral_file(conn, csv_path, log_key, batch_size, dry_run)
            else:
                logger.info("No pending spectral files found.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
