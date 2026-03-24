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
FOLDER_RE          = re.compile(r"^data_\d{8}$")
TEMP_FILE_RE       = re.compile(r"^m7004_ID_([0-9A-Fa-f]+)\.txt$")
IRRADIANCE_FILE_RE = re.compile(r"^PT-104_channel_(\d+)\.txt$")
SPECTRAL_FILE_RE   = re.compile(r"^\d{10}\.CSV$", re.IGNORECASE)

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

def ensure_registry(conn) -> int:
    """Idempotently create the PeroCube tracker and all 240 slots. Returns tracker id."""
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
            ON CONFLICT (mpp_tracker_id, slot_code) DO NOTHING
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
    """Returns {slot_code: int} for every slot belonging to this tracker."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_code, id FROM mpp_tracking_slot WHERE mpp_tracker_id = %s",
            (tracker_id,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


# ---------------------------------------------------------------------------
# Sensor registry helpers (spectral, temperature, irradiance)
# ---------------------------------------------------------------------------

def upsert_spectral_sensor(conn, model: str, instrument: str, wavelengths: list) -> int:
    """
    Idempotently register a spectral sensor by model (= serial number).
    Updates wavelengths_nm on first ingestion if still NULL.
    Returns spectral_sensor.id (= sensor.id).
    """
    serial = model
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, wavelengths_nm FROM spectral_sensor WHERE serial_number = %s",
            (serial,),
        )
        row = cur.fetchone()
        if row:
            sensor_id, existing_wl = row
            if existing_wl is None and wavelengths:
                cur.execute(
                    "UPDATE spectral_sensor SET wavelengths_nm = %s WHERE id = %s",
                    (wavelengths, sensor_id),
                )
            return sensor_id

        cur.execute(
            "INSERT INTO sensor (sensor_type) VALUES ('spectral') RETURNING id"
        )
        parent_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO spectral_sensor (id, name, model, instrument, serial_number, wavelengths_nm)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (parent_id, f"{instrument}_{model}", model, instrument, serial,
             wavelengths if wavelengths else None),
        )
        sensor_id = cur.fetchone()[0]
    conn.commit()
    return sensor_id


def upsert_temperature_sensor(conn, serial_number: str) -> int:
    """Idempotently register a temperature sensor by serial number. Returns temperature_sensor.id (= sensor.id)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM temperature_sensor WHERE serial_number = %s",
            (serial_number,),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        cur.execute(
            "INSERT INTO sensor (sensor_type) VALUES ('temperature') RETURNING id"
        )
        parent_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO temperature_sensor (id, name, model, serial_number)
            VALUES (%s, %s, 'm7004', %s)
            RETURNING id
            """,
            (parent_id, f"m7004_{serial_number}", serial_number),
        )
        sensor_id = cur.fetchone()[0]
    conn.commit()
    return sensor_id


def upsert_irradiance_sensor(conn, channel: str) -> int:
    """Idempotently register an irradiance sensor by channel. Returns irradiance_sensor.id (= sensor.id)."""
    serial = f"channel_{channel}"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM irradiance_sensor WHERE serial_number = %s",
            (serial,),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        cur.execute(
            "INSERT INTO sensor (sensor_type) VALUES ('irradiance') RETURNING id"
        )
        parent_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO irradiance_sensor (id, name, model, serial_number)
            VALUES (%s, %s, 'PT-104', %s)
            RETURNING id
            """,
            (parent_id, f"PT-104_{serial}", serial),
        )
        sensor_id = cur.fetchone()[0]
    conn.commit()
    return sensor_id


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
                current = float(row[2])
                voltage = float(row[3])
                rows.append((ts, power, current, voltage))
            except (ValueError, OverflowError) as exc:
                logger.warning(
                    "Skipping invalid row %d in %s: %s", lineno, file_path, exc
                )
    return rows


def parse_temperature_file(file_path: Path) -> list:
    """
    Parses a TSV file with columns: timestamp, temperature[°C].
    Returns list of (datetime, float) tuples.
    Malformed rows are skipped with a WARNING log.
    """
    rows = []
    with open(file_path, "r") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for lineno, row in enumerate(reader, 1):
            if len(row) != 2:
                logger.warning(
                    "Skipping malformed row %d in %s (expected 2 columns, got %d)",
                    lineno, file_path, len(row),
                )
                continue
            try:
                ts          = datetime.datetime.fromisoformat(row[0])
                ts          = ts.replace(tzinfo=datetime.timezone.utc)
                temperature = float(row[1])
                rows.append((ts, temperature))
            except (ValueError, OverflowError) as exc:
                logger.warning(
                    "Skipping invalid row %d in %s: %s", lineno, file_path, exc
                )
    return rows


def parse_irradiance_file(file_path: Path) -> list:
    """
    Parses a TSV file with columns: timestamp, raw_value[uV], irradiance[W/m²].
    Returns list of (datetime, int, float) tuples.
    Malformed rows are skipped with a WARNING log.
    """
    rows = []
    with open(file_path, "r") as fh:
        reader = csv.reader(fh, delimiter="\t")
        for lineno, row in enumerate(reader, 1):
            if len(row) != 3:
                logger.warning(
                    "Skipping malformed row %d in %s (expected 3 columns, got %d)",
                    lineno, file_path, len(row),
                )
                continue
            try:
                ts         = datetime.datetime.fromisoformat(row[0])
                ts         = ts.replace(tzinfo=datetime.timezone.utc)
                raw_value  = int(row[1])
                irradiance = float(row[2])
                rows.append((ts, raw_value, irradiance))
            except (ValueError, OverflowError) as exc:
                logger.warning(
                    "Skipping invalid row %d in %s: %s", lineno, file_path, exc
                )
    return rows


def parse_spectral_file(file_path: Path) -> dict:
    """
    Parses an EKO WISER 35 wide-format CSV (8-row header, then wavelength data).

    CSV layout:
      Row 0: Date          — first data cell holds the date ('2026/02/01'); repeated at odd cols
      Row 1: Time          — time per column; only populated at odd columns, empty at even
      Row 2: Memo          — instrument name ('EKO WISER 35')
      Row 3: Sensor        — model name per column ('MS-711' or 'MS-712'), all 24 filled
      Row 4: Exposure Time — integer ms per column
      Row 5: Sensor Temp.  — float °C per column
      Row 6: Power(V)      — float V per column
      Row 7: Column labels — 'Wavelength(nm)', 'Irradiance(W/m2/um)' × 24
      Row 8+: Data         — wavelength in col 0; irradiance values in cols 1–24 (empty = inactive)

    Returns a dict keyed by sensor model:
        {
            model: {
                "instrument": str,
                "wavelengths": list[float],     # active wavelength axis (from first time slot)
                "measurements": list of (datetime, list[float], int|None, float|None, float|None)
                    # (time, irradiances, exposure_ms, temp_c, power_v)
            }
        }
    """
    with open(file_path, newline="") as fh:
        reader = list(csv.reader(fh))

    if len(reader) < 9:
        logger.warning("Spectral file %s has fewer than 9 rows — skipping", file_path)
        return {}

    sensor_row   = reader[3]
    exposure_row = reader[4]
    temp_row     = reader[5]
    power_row    = reader[6]

    n_data_cols = len(sensor_row) - 1  # exclude label column in col 0

    # Date and time only appear at odd column positions; fill forward to cover even (MS-712) columns
    def fill_forward(values):
        result, last = [], None
        for v in values:
            if v.strip():
                last = v.strip()
            result.append(last)
        return result

    dates     = fill_forward(reader[0][1:])
    times_ff  = fill_forward(reader[1][1:])
    memos     = fill_forward(reader[2][1:])
    models    = [v.strip() for v in sensor_row[1:]]
    exposures = [v.strip() for v in exposure_row[1:]]
    temps     = [v.strip() for v in temp_row[1:]]
    powers    = [v.strip() for v in power_row[1:]]

    def _safe_float(s):
        try:
            return float(s) if s else None
        except ValueError:
            return None

    def _safe_int(s):
        try:
            return int(float(s)) if s else None
        except ValueError:
            return None

    # Build per-column context
    col_ctx = []
    for i in range(n_data_cols):
        try:
            date_obj = datetime.datetime.strptime(dates[i], "%Y/%m/%d").date()
            time_obj = datetime.time.fromisoformat(times_ff[i])
            ts = datetime.datetime.combine(date_obj, time_obj, tzinfo=datetime.timezone.utc)
        except (ValueError, IndexError, TypeError):
            col_ctx.append(None)
            continue

        col_ctx.append({
            "ts":      ts,
            "model":   models[i]    if i < len(models)    else None,
            "instr":   memos[i]     if i < len(memos)     else "EKO WISER 35",
            "exp_ms":  _safe_int(exposures[i]  if i < len(exposures) else ""),
            "temp_c":  _safe_float(temps[i]    if i < len(temps)     else ""),
            "power_v": _safe_float(powers[i]   if i < len(powers)    else ""),
        })

    # Build the full wavelength axis from col 0 (instrument-defined, e.g. 300–1800 nm at 1 nm).
    # This is sensor-independent; inactive wavelengths get NaN in the irradiance arrays so that
    # every measurement row stays aligned with wavelengths_nm regardless of sensor type or file.
    all_wavelengths = []
    for data_row in reader[8:]:
        if not data_row or not data_row[0].strip():
            continue
        try:
            all_wavelengths.append(float(data_row[0]))
        except ValueError:
            pass

    wl_index = {wl: idx for idx, wl in enumerate(all_wavelengths)}
    col_irr = [[float("nan")] * len(all_wavelengths) for _ in range(n_data_cols)]

    for data_row in reader[8:]:
        if not data_row or not data_row[0].strip():
            continue
        try:
            wl = float(data_row[0])
        except ValueError:
            continue
        idx = wl_index[wl]
        for i in range(n_data_cols):
            cell_idx = i + 1
            if cell_idx >= len(data_row):
                break
            cell = data_row[cell_idx].strip()
            if cell:
                try:
                    col_irr[i][idx] = float(cell)
                except ValueError:
                    pass

    # Group by model; all models share the full wavelength axis.
    result = {}
    for i, ctx in enumerate(col_ctx):
        if ctx is None or not ctx["model"]:
            continue
        model = ctx["model"]
        instr = ctx["instr"] or "EKO WISER 35"
        irradiances = col_irr[i]
        # Skip column only if every value is NaN (truly empty column)
        if all(v != v for v in irradiances):
            continue

        wavelengths = all_wavelengths

        if model not in result:
            result[model] = {
                "instrument":   instr,
                "wavelengths":  wavelengths,
                "measurements": [],
            }

        result[model]["measurements"].append(
            (ctx["ts"], irradiances, ctx["exp_ms"], ctx["temp_c"], ctx["power_v"])
        )

    return result


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
        # File column order: power, current, voltage → map to DB column order
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


def ingest_temperature_measurements(cur, sensor_id: int, rows: list, batch_size: int, dry_run: bool) -> int:
    """Inserts temperature rows in batches. Returns count of rows actually written."""
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        batch_data = [(ts, sensor_id, temperature) for ts, temperature in batch]
        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d temperature rows for sensor %s",
                len(batch_data), sensor_id,
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


def ingest_irradiance_measurements(cur, sensor_id: int, rows: list, batch_size: int, dry_run: bool) -> int:
    """Inserts irradiance rows in batches. Returns count of rows actually written."""
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        batch_data = [(ts, sensor_id, irradiance, raw_value) for ts, raw_value, irradiance in batch]
        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d irradiance rows for sensor %s",
                len(batch_data), sensor_id,
            )
            continue
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO irradiance_measurement (time, irradiance_sensor_id, irradiance, raw_value)
            VALUES %s
            ON CONFLICT (irradiance_sensor_id, time) DO NOTHING
            """,
            batch_data,
            page_size=len(batch_data),
        )
        inserted += cur.rowcount
    return inserted


def ingest_spectral_measurements(cur, sensor_id: int, rows: list, batch_size: int, dry_run: bool) -> int:
    """
    Batch-inserts spectral measurement rows. One row per (sensor, timestamp).
    rows: list of (datetime, irradiances, exposure_ms, temp_c, power_v)
    Returns count of rows actually written.
    """
    inserted = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        batch_data = [
            (ts, sensor_id, irr_list, exp_ms, temp_c, power_v)
            for ts, irr_list, exp_ms, temp_c, power_v in batch
        ]
        if dry_run:
            logger.info(
                "[DRY RUN] Would insert %d spectral rows for sensor %s",
                len(batch_data), sensor_id,
            )
            continue
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO spectral_measurement
                (time, spectral_sensor_id, irradiance_w_m2_um,
                 exposure_time_ms, sensor_temp_c, power_v)
            VALUES %s
            ON CONFLICT (spectral_sensor_id, time) DO NOTHING
            """,
            batch_data,
            page_size=len(batch_data),
        )
        inserted += cur.rowcount
    return inserted


# ---------------------------------------------------------------------------
# Folder ingestion
# ---------------------------------------------------------------------------

def ingest_mpp_folder(conn, slot_map: dict, folder_path: Path, batch_size: int, dry_run: bool) -> int:
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
                    "Committed %d new MPP rows from %s/%s (parsed %d)",
                    n, folder_path.parent.name, file_path.name, len(rows),
                )
            except Exception:
                conn.rollback()
                logger.exception("Failed to ingest %s — rolled back", file_path.name)
                raise

    return total_inserted


def ingest_temperature_folder(conn, folder_path: Path, batch_size: int, dry_run: bool) -> int:
    """
    Processes all m7004 temperature files within a folder.
    Upserts sensor registry entry per file, then inserts measurements.
    One transaction per file.
    """
    total_inserted = 0
    for file_path in sorted(folder_path.iterdir()):
        m = TEMP_FILE_RE.match(file_path.name)
        if not m:
            continue
        serial    = m.group(1)
        sensor_id = upsert_temperature_sensor(conn, serial)

        rows = parse_temperature_file(file_path)
        if not rows:
            logger.info("No valid rows in %s", file_path.name)
            continue

        try:
            with conn.cursor() as cur:
                n = ingest_temperature_measurements(cur, sensor_id, rows, batch_size, dry_run)
            conn.commit()
            total_inserted += n
            logger.info(
                "Committed %d new temperature rows from %s/%s (parsed %d)",
                n, folder_path.parent.name, file_path.name, len(rows),
            )
        except Exception:
            conn.rollback()
            logger.exception("Failed to ingest %s — rolled back", file_path.name)
            raise

    return total_inserted


def ingest_irradiance_folder(conn, folder_path: Path, batch_size: int, dry_run: bool) -> int:
    """
    Processes all PT-104 irradiance files within a folder.
    Upserts sensor registry entry per file, then inserts measurements.
    One transaction per file.
    """
    total_inserted = 0
    for file_path in sorted(folder_path.iterdir()):
        m = IRRADIANCE_FILE_RE.match(file_path.name)
        if not m:
            continue
        channel   = m.group(1)
        sensor_id = upsert_irradiance_sensor(conn, channel)

        rows = parse_irradiance_file(file_path)
        if not rows:
            logger.info("No valid rows in %s", file_path.name)
            continue

        try:
            with conn.cursor() as cur:
                n = ingest_irradiance_measurements(cur, sensor_id, rows, batch_size, dry_run)
            conn.commit()
            total_inserted += n
            logger.info(
                "Committed %d new irradiance rows from %s/%s (parsed %d)",
                n, folder_path.parent.name, file_path.name, len(rows),
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
        n  = ingest_mpp_folder(conn, slot_map, folder_path, batch_size, dry_run)
        n += ingest_temperature_folder(conn, folder_path, batch_size, dry_run)
        n += ingest_irradiance_folder(conn, folder_path, batch_size, dry_run)
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
# Spectral file ingestion
# ---------------------------------------------------------------------------

def discover_pending_spectral_files(conn, spectral_root: Path) -> list:
    """Returns CSV paths under spectral_root not yet marked completed in ingestion_log."""
    all_files = sorted(
        f for f in spectral_root.rglob("*.CSV")
        if SPECTRAL_FILE_RE.match(f.name)
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT folder_name FROM ingestion_log WHERE status = 'completed'"
        )
        completed_keys = {row[0] for row in cur.fetchall()}

    return [
        f for f in all_files
        if f"spectral:{f.relative_to(spectral_root)}" not in completed_keys
    ]


def ingest_spectral_file(conn, csv_path: Path, log_key: str, batch_size: int, dry_run: bool):
    """Wraps spectral file parsing and insertion with ingestion_log lifecycle management."""
    log_id = None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_log (folder_name, status) VALUES (%s, 'started') RETURNING id",
            (log_key,),
        )
        log_id = cur.fetchone()[0]
    conn.commit()

    try:
        sensor_data = parse_spectral_file(csv_path)
        if not sensor_data:
            logger.info("No valid data in %s", csv_path.name)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE ingestion_log
                    SET status='completed', completed_at=now(), rows_inserted=0
                    WHERE id=%s
                    """,
                    (log_id,),
                )
            conn.commit()
            return

        total_inserted = 0
        for model, info in sensor_data.items():
            sensor_id = upsert_spectral_sensor(
                conn, model, info["instrument"], info["wavelengths"]
            )
            with conn.cursor() as cur:
                n = ingest_spectral_measurements(
                    cur, sensor_id, info["measurements"], batch_size, dry_run
                )
            conn.commit()
            total_inserted += n
            logger.info(
                "Committed %d new spectral rows from %s (model=%s, parsed=%d)",
                n, csv_path.name, model, len(info["measurements"]),
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_log
                SET status='completed', completed_at=now(), rows_inserted=%s
                WHERE id=%s
                """,
                (total_inserted, log_id),
            )
        conn.commit()
        logger.info("Spectral file %s completed: %d new rows inserted", log_key, total_inserted)

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
        logger.error("Spectral file %s failed: %s", log_key, error_msg)


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

        if pending:
            logger.info("%d pending folder(s): %s", len(pending), pending)
            for folder_name in pending:
                process_folder(conn, slot_map, folder_name, data_root, batch_size, dry_run)
        else:
            logger.info("No pending folders found.")

        spectral_root = data_root / "spectral_data"
        if spectral_root.is_dir():
            pending_spectral = discover_pending_spectral_files(conn, spectral_root)
            if pending_spectral:
                logger.info(
                    "%d pending spectral file(s): %s",
                    len(pending_spectral), [str(p) for p in pending_spectral],
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
