"""End-to-end ingestion tests against a database with the migrations applied.

Run only against a local/CI database, never production:

    INGEST_TEST_DB=1 PGHOST=localhost PGPORT=5440 PGDATABASE=outdoor_dev PGUSER=dev PGPASSWORD=dev pytest -m db

The tests write rows dated 1999 and delete them afterwards.
"""
import datetime
import os

import pytest

pytestmark = pytest.mark.db

UTC = datetime.timezone.utc
SLOT = "PC01_board01_channel01"
TEMP_SERIAL = "00000000000000A0"
OLD_SERIALS = ("TESTOLD0000000A1", "TESTOLD0000000A2")


def utc(*args):
    return datetime.datetime(*args, tzinfo=UTC)


@pytest.fixture(scope="module")
def conn():
    if os.environ.get("INGEST_TEST_DB") != "1":
        pytest.skip("set INGEST_TEST_DB=1 to run database tests")
    if os.environ.get("PGHOST", "") not in ("localhost", "127.0.0.1", "postgres"):
        pytest.skip("refusing to run database tests against a non-local host")
    from db import get_connection

    connection = get_connection()
    yield connection
    _cleanup(connection)
    connection.close()


def _cleanup(connection):
    with connection.cursor() as cur:
        cur.execute("DELETE FROM mpp_measurement WHERE timestamp < '2000-01-01'")
        cur.execute("DELETE FROM temperature_measurement WHERE timestamp < '2000-01-01'")
        cur.execute("DELETE FROM irradiance_measurement WHERE timestamp < '2000-01-01'")
        cur.execute("DELETE FROM ingestion_log WHERE folder_name LIKE 'data_1999%' OR folder_name LIKE 'all_1999%'")
    connection.commit()


@pytest.fixture(autouse=True)
def clean(conn):
    _cleanup(conn)
    yield


def _slot_map(conn):
    from registry import build_slot_map, ensure_registry

    return build_slot_map(conn, ensure_registry(conn))


def _scalar(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def _timestamps(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [r[0] for r in cur.fetchall()]


def _run(conn, root, folder):
    from ingest import process_folder

    process_folder(conn, _slot_map(conn), folder, root, 1000, False)
    return _scalar(conn, "SELECT status FROM ingestion_log WHERE folder_name=%s ORDER BY id DESC LIMIT 1", (folder,)), \
        _scalar(conn, "SELECT rows_inserted FROM ingestion_log WHERE folder_name=%s ORDER BY id DESC LIMIT 1", (folder,))


def test_daily_export_is_stored_as_utc_and_ingestion_is_idempotent(conn, tmp_path):
    root = tmp_path / "mppt_temp_irr"
    data = root / "data_19990709" / "data"
    data.mkdir(parents=True)
    # one winter and one summer reading per file, in local time, CRLF as the real files
    (data / "output_board1_channel1.txt").write_bytes(
        b"1999-01-15T10:00:00\t0.5\t0.2\t0.4\r\n1999-07-09T10:00:00\t0.6\t0.3\t0.5\r\n")
    (data / f"m7004_ID_{TEMP_SERIAL}.txt").write_bytes(
        b"1999-01-15T10:00:00\t10.5\r\n1999-07-09T10:00:00\t25.5\r\n")
    (data / "PT-104_channel_01.txt").write_bytes(
        b"1999-01-15T10:00:00\t1000\t0.5\r\n1999-07-09T10:00:00\t2000\t1.5\r\n")

    status, rows = _run(conn, root, "data_19990709")
    assert status == "completed" and rows == 6

    expected = [utc(1999, 1, 15, 9, 0, 0), utc(1999, 7, 9, 8, 0, 0)]
    assert _timestamps(conn, """SELECT m.timestamp FROM mpp_measurement m JOIN mpp_tracking_slot s
                                ON s.id=m.mpp_tracking_slot_id WHERE s.slot_code=%s
                                AND m.timestamp < '2000-01-01' ORDER BY 1""", (SLOT,)) == expected
    assert _timestamps(conn, """SELECT m.timestamp FROM temperature_measurement m
                                JOIN temperature_sensor t ON t.id=m.temperature_sensor_id
                                WHERE t.serial_number=%s AND m.timestamp < '2000-01-01' ORDER BY 1""",
                       (TEMP_SERIAL,)) == expected
    assert _timestamps(conn, """SELECT m.timestamp FROM irradiance_measurement m
                                WHERE m.timestamp < '2000-01-01' ORDER BY 1""") == expected

    # Re-ingest the way an operator does: drop the log entry, let the next run pick it up.
    with conn.cursor() as cur:
        cur.execute("DELETE FROM ingestion_log WHERE folder_name = 'data_19990709'")
    conn.commit()
    status, rows = _run(conn, root, "data_19990709")        # nothing new the second time
    assert status == "completed" and rows == 0
    assert _scalar(conn, "SELECT count(*) FROM mpp_measurement WHERE timestamp < '2000-01-01'") == 2


def test_early_export_with_temperature_csv(conn, tmp_path):
    root = tmp_path / "mppt_temp_irr"
    folder = root / "all_19990709"
    folder.mkdir(parents=True)
    (folder / "output_board1_channel1.txt").write_text(
        "1999-01-15T10:00:00\t0.5\t0.2\t0.4\n1999-07-09T10:00:00\t0.6\t0.3\t0.5\n")
    (folder / "TemperatureLog_started_1999-01-15_09-00-00.csv").write_text(
        f"time, {OLD_SERIALS[0]}, {OLD_SERIALS[1]}\n"
        "1999-01-15T10:00:00,12.5,13.5\n"
        "1999-07-09T10:00:00,30.5,31.5\n")
    (folder / "IDs___1999-01-15_09-00-00.csv").write_text("port,channel,ID\n0,0,X\n")   # ignored
    (folder / "errorLog.txt").write_text("1999-01-15T10:00:00\t-1\tRead\n")             # ignored

    status, rows = _run(conn, root, "all_19990709")
    assert status == "completed" and rows == 2 + 4

    for serial, first in zip(OLD_SERIALS, (12.5, 13.5)):
        # the serial must not carry the space that follows the comma in the header
        got = _scalar(conn, "SELECT count(*) FROM temperature_sensor WHERE serial_number=%s", (serial,))
        assert got == 1
        assert _scalar(conn, """SELECT m.temperature FROM temperature_measurement m
                                JOIN temperature_sensor t ON t.id=m.temperature_sensor_id
                                WHERE t.serial_number=%s ORDER BY m.timestamp LIMIT 1""", (serial,)) == first
    assert _timestamps(conn, """SELECT m.timestamp FROM temperature_measurement m
                                JOIN temperature_sensor t ON t.id=m.temperature_sensor_id
                                WHERE t.serial_number=%s ORDER BY 1""", (OLD_SERIALS[0],)) == \
        [utc(1999, 1, 15, 9, 0, 0), utc(1999, 7, 9, 8, 0, 0)]
