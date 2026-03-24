import os
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import streamlit as st


def get_connection():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "outdoor_monitoring"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", "postgres"),
    )


@st.cache_data(ttl=30)
def load_cells():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM solar_cell ORDER BY name")
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_cells_full():
    with (
        get_connection() as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute(
            """
            SELECT
                sc.id,
                sc.name,
                sc.area_cm2,
                COALESCE(mfr.name || CASE WHEN mfr.affiliation <> '' THEN ' (' || mfr.affiliation || ')' ELSE '' END, '')
                    AS manufacturer,
                COALESCE(owner.name || CASE WHEN owner.affiliation <> '' THEN ' (' || owner.affiliation || ')' ELSE '' END, '')
                    AS owner,
                grp.name AS group_name,
                gt.code AS group_type,
                sc.position_in_group
            FROM solar_cell sc
            LEFT JOIN scientist mfr ON mfr.id = sc.manufacturer_id
            LEFT JOIN scientist owner ON owner.id = sc.owner_id
            LEFT JOIN solar_cell_group grp ON grp.id = sc.group_id
            LEFT JOIN solar_cell_group_type gt ON gt.id = grp.group_type_id
            ORDER BY sc.name
            """
        )
        return [dict(row) for row in cur.fetchall()]


@st.cache_data(ttl=30)
def load_recent_cells(limit=10):
    with (
        get_connection() as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute(
            """
            SELECT id, name, area_cm2, position_in_group
            FROM solar_cell
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


@st.cache_data(ttl=30)
def load_trackers():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM mpp_tracker ORDER BY name, id")
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_slots(tracker_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, slot_code
            FROM mpp_tracking_slot
            WHERE mpp_tracker_id = %s
            ORDER BY slot_code
            """,
            (tracker_id,),
        )
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_modes():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, code FROM mpp_connection_mode ORDER BY code")
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_scientists():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, name, affiliation FROM scientist ORDER BY name, affiliation"
        )
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_groups():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT g.id, g.name, gt.code
            FROM solar_cell_group g
            JOIN solar_cell_group_type gt ON gt.id = g.group_type_id
            ORDER BY g.name
            """
        )
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_groups_full():
    with (
        get_connection() as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute(
            """
            SELECT
                g.id,
                g.name,
                gt.code AS group_type,
                g.fabrication_date,
                COALESCE(mfr.name || CASE WHEN mfr.affiliation <> '' THEN ' (' || mfr.affiliation || ')' ELSE '' END, '')
                    AS manufacturer,
                rep.name AS representative_cell,
                g.notes
            FROM solar_cell_group g
            JOIN solar_cell_group_type gt ON gt.id = g.group_type_id
            LEFT JOIN scientist mfr ON mfr.id = g.manufacturer_id
            LEFT JOIN solar_cell rep ON rep.id = g.cell_id
            ORDER BY g.name
            """
        )
        return [dict(row) for row in cur.fetchall()]


@st.cache_data(ttl=30)
def load_group_types():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, code, description FROM solar_cell_group_type ORDER BY code"
        )
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_projects():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM project ORDER BY name")
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_experiments():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM experiment ORDER BY name")
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_experiments_with_projects():
    with (
        get_connection() as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute(
            """
            SELECT
                e.id,
                e.name,
                COALESCE(STRING_AGG(DISTINCT p.name, ', ' ORDER BY p.name), '') AS projects
            FROM experiment e
            LEFT JOIN experiment_project ep ON ep.experiment_id = e.id
            LEFT JOIN project p ON p.id = ep.project_id
            GROUP BY e.id, e.name
            ORDER BY e.name
            """
        )
        return [dict(row) for row in cur.fetchall()]


def load_cell_by_id(cell_id):
    with (
        get_connection() as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute(
            "SELECT * FROM solar_cell WHERE id = %s",
            (cell_id,),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def load_sensors():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                s.id,
                s.sensor_type,
                COALESCE(ts.name, ir.name, sp.name) AS name,
                COALESCE(ts.serial_number, ir.serial_number, sp.serial_number) AS serial_number,
                COALESCE(ts.location, ir.location, sp.location) AS location
            FROM sensor s
            LEFT JOIN temperature_sensor ts ON ts.id = s.id
            LEFT JOIN irradiance_sensor ir ON ir.id = s.id
            LEFT JOIN spectral_sensor sp ON sp.id = s.id
            ORDER BY s.sensor_type, name, s.id
            """
        )
        return cur.fetchall()


def load_experiment_cells(experiment_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT sc.id, sc.name
            FROM solar_cell_experiment sce
            JOIN solar_cell sc ON sc.id = sce.solar_cell_id
            WHERE sce.experiment_id = %s
            ORDER BY sc.name
            """,
            (experiment_id,),
        )
        return cur.fetchall()


def current_slot_for_cell(cell_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.event_type, s.id, s.slot_code, t.name
            FROM mpp_connection_event e
            JOIN mpp_tracking_slot s ON s.id = e.mpp_tracking_slot_id
            JOIN mpp_tracker t ON t.id = s.mpp_tracker_id
            WHERE e.solar_cell_id = %s
            ORDER BY e.occurred_at DESC, e.id DESC
            LIMIT 1
            """,
            (cell_id,),
        )
        row = cur.fetchone()
        if row is None or row[0] != "connection":
            return None
        return row[1], row[2], row[3]


def current_slot_id(cell_id):
    current = current_slot_for_cell(cell_id)
    if current is None:
        return None
    return current[0], current[1]


def current_sensors_for_cell(cell_id):
    with (
        get_connection() as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute(
            """
            WITH latest AS (
                SELECT DISTINCT ON (e.sensor_id)
                    e.sensor_id,
                    e.event_type,
                    s.sensor_type,
                    COALESCE(ts.name, ir.name, sp.name) AS name
                FROM sensor_association_event e
                JOIN sensor s ON s.id = e.sensor_id
                LEFT JOIN temperature_sensor ts ON ts.id = s.id
                LEFT JOIN irradiance_sensor ir ON ir.id = s.id
                LEFT JOIN spectral_sensor sp ON sp.id = s.id
                WHERE e.solar_cell_id = %s
                ORDER BY e.sensor_id, e.occurred_at DESC, e.id DESC
            )
            SELECT sensor_id, sensor_type, name
            FROM latest
            WHERE event_type = 'association'
            ORDER BY sensor_type, name, sensor_id
            """,
            (cell_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def cells_exist(names):
    normalized = sorted({name.strip() for name in names if name and name.strip()})
    if not normalized:
        return set()
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT name FROM solar_cell WHERE name = ANY(%s)",
            (normalized,),
        )
        return {row[0] for row in cur.fetchall()}


def tracker_status_snapshot(tracker_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT name FROM mpp_tracker WHERE id = %s", (tracker_id,))
        row = cur.fetchone()
        if row is None:
            return []
        cur.execute(
            "SELECT slot_code, is_connected, cell_name, mode_code, connected_since FROM mpp_tracker_status(%s)",
            (row[0],),
        )
        return cur.fetchall()


def ensure_cell(name):
    cell_name = name.strip()
    if not cell_name:
        raise ValueError("Cell name is required.")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO solar_cell (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (cell_name,),
        )
        cur.execute("SELECT id FROM solar_cell WHERE name = %s", (cell_name,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Could not find or create solar_cell '{cell_name}'")
        return row[0]


def insert_events(rows):
    if not rows:
        return
    with get_connection() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO mpp_connection_event
                (event_type, mode_id, occurred_at, solar_cell_id, mpp_tracking_slot_id)
            VALUES (%(event_type)s, %(mode_id)s, %(occurred_at)s, %(cell_id)s, %(slot_id)s)
            """,
            rows,
        )
        conn.commit()


def upsert_scientist(name, affiliation):
    scientist_name = name.strip()
    scientist_affiliation = (affiliation or "").strip()
    if not scientist_name:
        raise ValueError("Scientist name is required.")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO scientist (name, affiliation)
            VALUES (%s, %s)
            ON CONFLICT (name, affiliation) DO NOTHING
            """,
            (scientist_name, scientist_affiliation),
        )
        cur.execute(
            "SELECT id FROM scientist WHERE name = %s AND affiliation = %s",
            (scientist_name, scientist_affiliation),
        )
        return cur.fetchone()[0]


def insert_group(name, group_type_id, fabrication_date, manufacturer_id, notes):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO solar_cell_group
                (name, group_type_id, fabrication_date, manufacturer_id, notes)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name.strip(),
                group_type_id,
                fabrication_date,
                manufacturer_id,
                notes or None,
            ),
        )
        return cur.fetchone()[0]


def update_group_cell_id(group_id, cell_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE solar_cell_group SET cell_id = %s WHERE id = %s",
            (cell_id, group_id),
        )
        conn.commit()


def insert_cell(name, area_cm2, manufacturer_id, owner_id, group_id, position_in_group):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO solar_cell
                (name, area_cm2, manufacturer_id, owner_id, group_id, position_in_group)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name.strip(),
                area_cm2,
                manufacturer_id,
                owner_id,
                group_id,
                position_in_group or None,
            ),
        )
        return cur.fetchone()[0]


def update_cell_metadata(
    cell_id, area_cm2, manufacturer_id, owner_id, group_id, position_in_group
):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE solar_cell
            SET area_cm2 = %s,
                manufacturer_id = %s,
                owner_id = %s,
                group_id = %s,
                position_in_group = %s
            WHERE id = %s
            """,
            (
                area_cm2,
                manufacturer_id,
                owner_id,
                group_id,
                position_in_group or None,
                cell_id,
            ),
        )
        conn.commit()


def upsert_project(name):
    project_name = name.strip()
    if not project_name:
        raise ValueError("Project name is required.")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO project (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (project_name,),
        )
        cur.execute("SELECT id FROM project WHERE name = %s", (project_name,))
        return cur.fetchone()[0]


def upsert_experiment(name):
    experiment_name = name.strip()
    if not experiment_name:
        raise ValueError("Experiment name is required.")
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO experiment (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (experiment_name,),
        )
        cur.execute("SELECT id FROM experiment WHERE name = %s", (experiment_name,))
        return cur.fetchone()[0]


def link_experiment_project(experiment_id, project_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO experiment_project (experiment_id, project_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (experiment_id, project_id),
        )
        conn.commit()


def link_cell_experiment(solar_cell_id, experiment_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO solar_cell_experiment (solar_cell_id, experiment_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (solar_cell_id, experiment_id),
        )
        conn.commit()


def insert_sensor_association_events(rows):
    if not rows:
        return
    with get_connection() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO sensor_association_event
                (event_type, specification, occurred_at, solar_cell_id, sensor_id)
            VALUES (%(event_type)s, %(specification)s, %(occurred_at)s, %(cell_id)s, %(sensor_id)s)
            """,
            rows,
        )
        conn.commit()


def system_summary():
    with (
        get_connection() as conn,
        conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur,
    ):
        cur.execute(
            """
            WITH latest_connections AS (
                SELECT DISTINCT ON (solar_cell_id)
                    solar_cell_id,
                    event_type
                FROM mpp_connection_event
                ORDER BY solar_cell_id, occurred_at DESC, id DESC
            )
            SELECT
                (SELECT COUNT(*) FROM solar_cell) AS cell_count,
                (SELECT COUNT(*) FROM solar_cell_group) AS group_count,
                (SELECT COUNT(*) FROM scientist) AS scientist_count,
                (SELECT COUNT(*) FROM project) AS project_count,
                (SELECT COUNT(*) FROM experiment) AS experiment_count,
                (SELECT COUNT(*) FROM latest_connections WHERE event_type = 'connection') AS active_connections
            """
        )
        return dict(cur.fetchone())


def parse_board_channel(slot_code):
    try:
        parts = slot_code.split("_")
        board = int(
            next(part for part in parts if part.startswith("board")).replace(
                "board", ""
            )
        )
        channel = int(
            next(part for part in parts if part.startswith("channel")).replace(
                "channel", ""
            )
        )
        return board, channel
    except (StopIteration, ValueError, AttributeError):
        return None


def to_timestamptz(d, event_type):
    if event_type in {"connection", "association"}:
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)
