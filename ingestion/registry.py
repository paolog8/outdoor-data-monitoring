import logging

import psycopg2.extras

from constants import BOARDS, CHANNELS, SLOT_CODE_PATTERN, TRACKER_MODEL, TRACKER_NAME

logger = logging.getLogger(__name__)


def ensure_registry(conn) -> int:
    """Idempotently create the PeroCube tracker and all 240 slots. Returns tracker id."""
    with conn.cursor() as cur:
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


def build_slot_map(conn, tracker_id) -> dict:
    """Returns {slot_code: int} for every slot belonging to this tracker."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT slot_code, id FROM mpp_tracking_slot WHERE mpp_tracker_id = %s",
            (tracker_id,),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


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
    """Idempotently register a temperature sensor by serial number. Returns temperature_sensor.id."""
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
    """Idempotently register an irradiance sensor by channel. Returns irradiance_sensor.id."""
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
