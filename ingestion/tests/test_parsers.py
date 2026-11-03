"""Parser tests (no database). Fixtures are lines cut from real export files.

The measurement software writes naive timestamps in local time (Europe/Berlin).
They must be stored as the matching UTC instant.
"""
import datetime
import logging
from pathlib import Path

import pytest

from constants import FOLDER_RE, FOLDER_RE_OLD, TEMP_FILE_OLD_RE
from irradiance import parse_irradiance_file
from mpp import parse_file as parse_mpp_file
from temperature import parse_temperature_csv, parse_temperature_file
from timeutil import local_to_utc

FIXTURES = Path(__file__).parent / "fixtures"
UTC = datetime.timezone.utc


def utc(*args):
    return datetime.datetime(*args, tzinfo=UTC)


# --- local_to_utc ---------------------------------------------------------

def test_local_to_utc_winter_is_one_hour_behind():
    assert local_to_utc(datetime.datetime(2025, 11, 14, 16, 45, 59)) == utc(2025, 11, 14, 15, 45, 59)


def test_local_to_utc_summer_is_two_hours_behind():
    assert local_to_utc(datetime.datetime(2025, 7, 10, 11, 51, 48)) == utc(2025, 7, 10, 9, 51, 48)


def test_local_to_utc_result_is_utc_aware():
    assert local_to_utc(datetime.datetime(2025, 7, 10, 12, 0)).utcoffset() == datetime.timedelta(0)


def test_local_to_utc_repeated_autumn_hour_takes_first_occurrence():
    # 2024-10-27 02:30 happens twice; the system does not record at night, so this only
    # documents the (deterministic) behaviour: the first, still-summer-time occurrence.
    assert local_to_utc(datetime.datetime(2024, 10, 27, 2, 30)) == utc(2024, 10, 27, 0, 30)


def test_local_to_utc_leaves_aware_timestamps_alone():
    aware = datetime.datetime(2025, 7, 10, 12, 0, tzinfo=UTC)
    assert local_to_utc(aware) == aware


# --- MPP files ------------------------------------------------------------

def test_mpp_winter_row_is_converted_to_utc():
    rows = parse_mpp_file(FIXTURES / "mpp_winter.txt")
    ts, power, current, voltage = rows[0]
    assert ts == utc(2025, 11, 14, 15, 45, 59)
    assert (power, current, voltage) == (0.000036, -0.021966, -0.001625)
    assert len(rows) == 3


def test_mpp_summer_row_is_converted_to_utc():
    rows = parse_mpp_file(FIXTURES / "mpp_summer.txt")
    ts, power, current, voltage = rows[0]
    assert ts == utc(2025, 7, 10, 9, 51, 48)
    assert (power, current, voltage) == (0.050979, 0.146439, 0.348125)


def test_mpp_skips_malformed_rows(tmp_path, caplog):
    f = tmp_path / "output_board1_channel1.txt"
    f.write_text(
        "2025-11-14T16:45:59\t0.1\t0.2\t0.3\n"
        "2025-11-14T16:46:29\t0.1\t0.2\n"            # too few columns
        "not-a-time\t0.1\t0.2\t0.3\n"                 # bad timestamp
        "2025-11-14T16:47:13\tabc\t0.2\t0.3\n"        # bad number
        "2025-11-14T16:47:44\t0.4\t0.5\t0.6\n"
    )
    with caplog.at_level(logging.WARNING):
        rows = parse_mpp_file(f)
    assert [r[0] for r in rows] == [utc(2025, 11, 14, 15, 45, 59), utc(2025, 11, 14, 15, 47, 44)]
    assert len(caplog.records) == 3


def test_mpp_empty_file_gives_no_rows(tmp_path):
    f = tmp_path / "output_board1_channel1.txt"
    f.write_text("")
    assert parse_mpp_file(f) == []


# --- temperature, irradiance ------------------------------------------------

def test_temperature_row_is_converted_to_utc():
    rows = parse_temperature_file(FIXTURES / "m7004_ID_1F00000B7284CF28.txt")
    assert rows[0] == (utc(2025, 11, 14, 15, 45, 59), 10.68)
    assert len(rows) == 3


def test_irradiance_row_is_converted_to_utc():
    rows = parse_irradiance_file(FIXTURES / "PT-104_channel_01.txt")
    assert rows[0] == (utc(2025, 11, 14, 15, 45, 59), -111687, -2.597)
    assert len(rows) == 3


# --- old temperature CSV (all_YYYYMMDD folders) -------------------------------

def test_old_temperature_csv_is_split_per_sensor_with_clean_names():
    data = parse_temperature_csv(FIXTURES / "TemperatureLog_sample.csv")
    # The header is "time, A100..., 3900..." (space after the comma): names must be stripped.
    assert sorted(data) == ["3900000A10BB0D28", "A100000A109B7628"]
    assert data["A100000A109B7628"][0] == (utc(2021, 11, 19, 16, 21, 12), 12.5)
    assert len(data["3900000A10BB0D28"]) == 2


def test_old_temperature_csv_skips_empty_and_invalid_cells(tmp_path):
    f = tmp_path / "TemperatureLog_started_2022-01-01_00-00-00.csv"
    f.write_text(
        "time, S1, S2\n"
        "2022-07-01T12:00:00,20.5,\n"                 # S2 empty
        "2022-07-01T12:00:30,nan,21.0\n"              # S1 NaN
        "bad-time,22.0,22.0\n"
        "2022-07-01T12:01:00,23.0,23.5\n"
    )
    data = parse_temperature_csv(f)
    assert data["S1"] == [(utc(2022, 7, 1, 10, 0, 0), 20.5), (utc(2022, 7, 1, 10, 1, 0), 23.0)]
    assert data["S2"] == [(utc(2022, 7, 1, 10, 0, 30), 21.0), (utc(2022, 7, 1, 10, 1, 0), 23.5)]


# --- folder / file name patterns ---------------------------------------------

@pytest.mark.parametrize("name", ["data_20240222", "data_20261029"])
def test_daily_export_folder_names(name):
    assert FOLDER_RE.match(name) and not FOLDER_RE_OLD.match(name)


@pytest.mark.parametrize("name", ["all_20211012", "all_20230609"])
def test_old_export_folder_names(name):
    assert FOLDER_RE_OLD.match(name) and not FOLDER_RE.match(name)


@pytest.mark.parametrize("name", ["test", "all_2021", "data_2024022", "all_20220821.zip", "data_20240222_bak"])
def test_other_names_are_not_export_folders(name):
    assert not FOLDER_RE.match(name) and not FOLDER_RE_OLD.match(name)


@pytest.mark.parametrize("name", [
    "TemperatureLog_started_2022-05-14_20-24-40.csv",
    "TemperatureLog2022-05-14_20-24-40.csv",
])
def test_old_temperature_file_names(name):
    assert TEMP_FILE_OLD_RE.match(name)


@pytest.mark.parametrize("name", ["IDs___2021-11-19_17-21-09.csv", "errorLog.txt", "all_20220609.zip"])
def test_other_old_files_are_ignored(name):
    assert not TEMP_FILE_OLD_RE.match(name)
