import os
from datetime import date, datetime, timezone

import psycopg2
import psycopg2.extras
import streamlit as st

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

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
        return cur.fetchall()  # [(id, name), ...]


@st.cache_data(ttl=30)
def load_trackers():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM mpp_tracker ORDER BY name")
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_slots(tracker_id):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, slot_code FROM mpp_tracking_slot "
            "WHERE mpp_tracker_id = %s ORDER BY slot_code",
            (tracker_id,),
        )
        return cur.fetchall()


@st.cache_data(ttl=30)
def load_modes():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, code FROM mpp_connection_mode ORDER BY code")
        return cur.fetchall()


def current_slot_id(cell_id):
    """Return (slot_id, slot_code) of the cell's current connection, or None."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT e.mpp_tracking_slot_id, s.slot_code
            FROM mpp_connection_event e
            JOIN mpp_tracking_slot s ON s.id = e.mpp_tracking_slot_id
            WHERE e.solar_cell_id = %s
            ORDER BY e.occurred_at DESC
            LIMIT 1
            """,
            (cell_id,),
        )
        row = cur.fetchone()
        return row  # (slot_id, slot_code) or None


def ensure_cell(name):
    """Insert the cell if it doesn't exist, return its id."""
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO solar_cell (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
        cur.execute("SELECT id FROM solar_cell WHERE name = %s", (name,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Could not find or create solar_cell '{name}'")
        return row[0]


def insert_events(rows):
    """
    rows: list of dicts with keys:
        cell_id, slot_id, event_type, mode_id, occurred_at
    """
    with get_connection() as conn, conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            """
            INSERT INTO mpp_connection_event
                (event_type, mode_id, occurred_at, solar_cell_id, mpp_tracking_slot_id)
            VALUES (%(event_type)s, %(mode_id)s, %(occurred_at)s,
                    %(cell_id)s, %(slot_id)s)
            """,
            rows,
        )
        conn.commit()


def to_timestamptz(d: date, event_type: str) -> datetime:
    if event_type == "connection":
        return datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=timezone.utc)
    else:
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "batch" not in st.session_state:
    st.session_state.batch = []  # list of {"cell_name": str, "slot_id": int|None, "slot_code": str}


def add_rows(names):
    existing = {r["cell_name"] for r in st.session_state.batch}
    for name in names:
        name = name.strip()
        if name and name not in existing:
            st.session_state.batch.append({"cell_name": name, "slot_id": None, "slot_code": ""})
            existing.add(name)


def remove_row(idx):
    st.session_state.batch.pop(idx)


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

st.set_page_config(page_title="MPP Connection Events", layout="wide")
st.title("MPP Connection Event Entry")

# ---- Sidebar: shared fields ------------------------------------------------
with st.sidebar:
    st.header("Event details")

    event_type = st.selectbox("Event type", ["connection", "disconnection"])
    event_date = st.date_input("Date", value=date.today())

    mode_id = None
    tracker_id = None
    slot_options = []   # [(slot_id, slot_code), ...]
    slot_codes = []     # just the codes for display

    if event_type == "connection":
        modes = load_modes()
        mode_names = [m[1] for m in modes]
        mode_sel = st.selectbox("Mode", mode_names)
        mode_id = next(m[0] for m in modes if m[1] == mode_sel)

        trackers = load_trackers()
        tracker_names = [t[1] for t in trackers]
        tracker_sel = st.selectbox("Tracker", tracker_names)
        tracker_id = next(t[0] for t in trackers if t[1] == tracker_sel)

        slot_options = load_slots(tracker_id)
        slot_codes = [s[1] for s in slot_options]

# ---- Main area: batch builder ----------------------------------------------
col_batch, col_manual = st.columns([2, 1])

with col_batch:
    st.subheader("Add by base name + suffixes")
    base = st.text_input("Base name", placeholder="SampleX_px")
    suffixes_raw = st.text_input("Suffixes (comma-separated)", placeholder="A,B,C,D")
    if st.button("Add to batch"):
        if base:
            suffixes = [s.strip() for s in suffixes_raw.split(",") if s.strip()]
            if suffixes:
                add_rows([f"{base}{s}" for s in suffixes])
            else:
                add_rows([base])

with col_manual:
    st.subheader("Add single cell")
    cells_db = load_cells()
    cell_names_db = [c[1] for c in cells_db]

    add_mode = st.radio("Cell", ["Existing", "New"], horizontal=True)
    if add_mode == "Existing":
        pick = st.selectbox("Select cell", cell_names_db, label_visibility="collapsed")
    else:
        pick = st.text_input("New cell name", label_visibility="collapsed")

    if st.button("Add row"):
        if pick:
            add_rows([pick])

# ---- Batch table -----------------------------------------------------------
st.divider()
st.subheader(f"Batch — {len(st.session_state.batch)} row(s)")

if not st.session_state.batch:
    st.info("No cells added yet. Use the controls above to build the batch.")
else:
    header_cols = st.columns([3, 3, 1])
    header_cols[0].markdown("**Cell name**")
    header_cols[1].markdown("**Slot**" if event_type == "connection" else "**Current slot (auto)**")
    header_cols[2].markdown("")

    rows_to_remove = []
    for i, row in enumerate(st.session_state.batch):
        c1, c2, c3 = st.columns([3, 3, 1])

        with c1:
            new_name = st.text_input(
                "cell", value=row["cell_name"], key=f"name_{i}", label_visibility="collapsed"
            )
            st.session_state.batch[i]["cell_name"] = new_name

        with c2:
            if event_type == "connection":
                if slot_codes:
                    current_code = row["slot_code"] if row["slot_code"] in slot_codes else slot_codes[0]
                    sel_code = st.selectbox(
                        "slot", slot_codes, index=slot_codes.index(current_code),
                        key=f"slot_{i}", label_visibility="collapsed"
                    )
                    slot_id = next(s[0] for s in slot_options if s[1] == sel_code)
                    st.session_state.batch[i]["slot_id"] = slot_id
                    st.session_state.batch[i]["slot_code"] = sel_code
                else:
                    st.warning("No slots for this tracker")
            else:
                # Auto-resolve from DB
                cell_id_lookup = next((c[0] for c in cells_db if c[1] == row["cell_name"]), None)
                if cell_id_lookup:
                    slot_info = current_slot_id(cell_id_lookup)
                    if slot_info:
                        st.session_state.batch[i]["slot_id"] = slot_info[0]
                        st.text(slot_info[1])
                    else:
                        st.warning("Not currently connected")
                        st.session_state.batch[i]["slot_id"] = None
                else:
                    st.caption("(new cell — no current slot)")
                    st.session_state.batch[i]["slot_id"] = None

        with c3:
            if st.button("✕", key=f"del_{i}"):
                rows_to_remove.append(i)

    for idx in reversed(rows_to_remove):
        remove_row(idx)
    if rows_to_remove:
        st.rerun()

# ---- Submit ----------------------------------------------------------------
st.divider()
if st.button("Submit events", type="primary", disabled=not st.session_state.batch):
    errors = []
    to_insert = []

    for row in st.session_state.batch:
        name = row["cell_name"].strip()
        if not name:
            errors.append("One or more rows have an empty cell name.")
            continue
        if event_type == "connection" and row["slot_id"] is None:
            errors.append(f"'{name}': no slot assigned.")
            continue
        if event_type == "disconnection" and row["slot_id"] is None:
            errors.append(f"'{name}': not currently connected — cannot disconnect.")
            continue
        to_insert.append(row)

    if errors:
        for e in errors:
            st.error(e)
    else:
        try:
            occurred_at = to_timestamptz(event_date, event_type)
            db_rows = []
            for row in to_insert:
                cell_id = ensure_cell(row["cell_name"])
                db_rows.append({
                    "cell_id": cell_id,
                    "slot_id": row["slot_id"],
                    "event_type": event_type,
                    "mode_id": mode_id,
                    "occurred_at": occurred_at,
                })
            insert_events(db_rows)
            st.cache_data.clear()
            st.success(f"Inserted {len(db_rows)} event(s).")
            st.session_state.batch = []
            st.rerun()
        except Exception as ex:
            st.error(f"Database error: {ex}")
