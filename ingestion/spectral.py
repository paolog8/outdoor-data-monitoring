import csv
import datetime
import logging
from pathlib import Path

import psycopg2.extras
from constants import SPECTRAL_FILE_RE
from registry import upsert_spectral_sensor

logger = logging.getLogger(__name__)

EXPECTED_ROW_LABELS = {
    0: "Date",
    1: "Time",
    2: "Memo",
    3: "Sensor",
    4: "Exposure Time",
    5: "Sensor Temp.",
    6: "Power(V)",
}


class SpectralFileStructureError(ValueError):
    """Raised when a spectral CSV does not match the expected EKO WISER 35 layout."""


def _strip_trailing_empty_column(reader: list) -> list:
    """
    EKO WISER 35 exports terminate every row with a trailing comma, producing
    an extra empty field beyond the documented columns. Drop it uniformly so
    column counts line up with the layout in `parse_spectral_file`.
    """
    if reader and all(not row or row[-1] == "" for row in reader):
        return [row[:-1] for row in reader]
    return reader


def validate_spectral_structure(reader: list) -> None:
    """
    Checks that `reader` (rows from an EKO WISER 35 CSV) matches the fixed
    layout documented in `parse_spectral_file`. Raises SpectralFileStructureError
    with a description of the mismatch if it does not.
    """
    if len(reader) < 9:
        raise SpectralFileStructureError(
            f"expected at least 9 header+data rows, got {len(reader)}"
        )

    for row_idx, expected_label in EXPECTED_ROW_LABELS.items():
        row = reader[row_idx]
        actual = row[0].strip() if row else ""
        if expected_label.lower() not in actual.lower():
            raise SpectralFileStructureError(
                f"row {row_idx} label is '{actual}', expected something containing '{expected_label}'"
            )

    header_row = reader[7]
    first_label = header_row[0].strip() if header_row else ""
    if first_label != "Wavelength(nm)":
        raise SpectralFileStructureError(
            f"row 7 col 0 is '{first_label}', expected 'Wavelength(nm)'"
        )
    if len(header_row) < 2 or any(
        "irradiance" not in cell.lower() for cell in header_row[1:]
    ):
        raise SpectralFileStructureError(
            "row 7 data columns are not all 'Irradiance(W/m2/um)'"
        )

    n_cols = len(reader[3])
    if n_cols < 2:
        raise SpectralFileStructureError(f"row 3 (Sensor) has only {n_cols} column(s)")
    for row_idx in range(8):
        if len(reader[row_idx]) != n_cols:
            raise SpectralFileStructureError(
                f"row {row_idx} has {len(reader[row_idx])} columns, expected {n_cols} (matching row 3)"
            )


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
      Row 7: Column labels — 'Wavelength(nm)', 'Irradiance(W/m2/um)' x 24
      Row 8+: Data         — wavelength in col 0; irradiance values in cols 1-24 (empty = inactive)

    Returns a dict keyed by sensor model:
        {
            model: {
                "instrument": str,
                "wavelengths": list[float],
                "measurements": list of (datetime, list[float], int|None, float|None, float|None)
            }
        }

    Raises:
        SpectralFileStructureError: if the file does not match the layout above.
            Callers must not treat a partial/best-effort parse as valid in this case.
    """
    with open(file_path, newline="") as fh:
        reader = list(csv.reader(fh))

    reader = _strip_trailing_empty_column(reader)

    validate_spectral_structure(reader)

    sensor_row = reader[3]
    exposure_row = reader[4]
    temp_row = reader[5]
    power_row = reader[6]

    n_data_cols = len(sensor_row) - 1

    # Date and time only appear at odd column positions; fill forward to cover even columns.
    def fill_forward(values):
        result, last = [], None
        for v in values:
            if v.strip():
                last = v.strip()
            result.append(last)
        return result

    dates = fill_forward(reader[0][1:])
    times_ff = fill_forward(reader[1][1:])
    memos = fill_forward(reader[2][1:])
    models = [v.strip() for v in sensor_row[1:]]
    exposures = [v.strip() for v in exposure_row[1:]]
    temps = [v.strip() for v in temp_row[1:]]
    powers = [v.strip() for v in power_row[1:]]

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

    col_ctx = []
    for i in range(n_data_cols):
        try:
            date_obj = datetime.datetime.strptime(dates[i], "%Y/%m/%d").date()
            time_obj = datetime.time.fromisoformat(times_ff[i])
            ts = datetime.datetime.combine(
                date_obj, time_obj, tzinfo=datetime.timezone.utc
            )
        except (ValueError, IndexError, TypeError):
            col_ctx.append(None)
            continue

        col_ctx.append(
            {
                "ts": ts,
                "model": models[i] if i < len(models) else None,
                "instr": memos[i] if i < len(memos) else "EKO WISER 35",
                "exp_ms": _safe_int(exposures[i] if i < len(exposures) else ""),
                "temp_c": _safe_float(temps[i] if i < len(temps) else ""),
                "power_v": _safe_float(powers[i] if i < len(powers) else ""),
            }
        )

    # Build the full wavelength axis from col 0. Inactive wavelengths get NaN so every
    # measurement row stays aligned with wavelengths_nm regardless of sensor type.
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

    result = {}
    for i, ctx in enumerate(col_ctx):
        if ctx is None or not ctx["model"]:
            continue
        model = ctx["model"]
        instr = ctx["instr"] or "EKO WISER 35"
        irradiances = col_irr[i]
        if all(v != v for v in irradiances):  # all NaN → truly empty column
            continue

        if model not in result:
            result[model] = {
                "instrument": instr,
                "wavelengths": all_wavelengths,
                "measurements": [],
            }

        result[model]["measurements"].append(
            (ctx["ts"], irradiances, ctx["exp_ms"], ctx["temp_c"], ctx["power_v"])
        )

    return result


def ingest_spectral_measurements(
    cur, sensor_id: int, rows: list, batch_size: int, dry_run: bool
) -> int:
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
                len(batch_data),
                sensor_id,
            )
            continue
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO spectral_measurement
                (timestamp, spectral_sensor_id, irradiance_w_m2_um,
                 exposure_time_ms, sensor_temp_c, power_v)
            VALUES %s
            ON CONFLICT (spectral_sensor_id, timestamp) DO NOTHING
            """,
            batch_data,
            page_size=len(batch_data),
        )
        inserted += cur.rowcount
    return inserted


def ingest_spectral_file(
    conn, csv_path: Path, log_key: str, batch_size: int, dry_run: bool
):
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
                n,
                csv_path.name,
                model,
                len(info["measurements"]),
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
        logger.info(
            "Spectral file %s completed: %d new rows inserted", log_key, total_inserted
        )

    except SpectralFileStructureError as exc:
        conn.rollback()
        error_msg = f"structure mismatch: {exc}"
        logger.error(
            "Spectral file %s does not match expected layout — skipping: %s",
            csv_path.name,
            exc,
        )
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


def discover_pending_spectral_files(conn, spectral_root: Path) -> list:
    """Returns CSV paths under spectral_root not yet marked completed in ingestion_log."""
    all_files = sorted(
        f for f in spectral_root.rglob("*.CSV") if SPECTRAL_FILE_RE.match(f.name)
    )
    with conn.cursor() as cur:
        cur.execute("SELECT folder_name FROM ingestion_log WHERE status = 'completed'")
        completed_keys = {row[0] for row in cur.fetchall()}

    return [
        f
        for f in all_files
        if f"spectral:{f.relative_to(spectral_root)}" not in completed_keys
    ]
