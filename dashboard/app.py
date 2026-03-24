import streamlit as st

from db import load_recent_cells, load_trackers, system_summary, tracker_status_snapshot


st.set_page_config(page_title="Outdoor PV Monitor", layout="wide")
st.title("Outdoor PV Monitoring System")


summary = system_summary()
metric_columns = st.columns(6)
metrics = [
    ("Cells", summary["cell_count"]),
    ("Groups", summary["group_count"]),
    ("Scientists", summary["scientist_count"]),
    ("Projects", summary["project_count"]),
    ("Experiments", summary["experiment_count"]),
    ("Active connections", summary["active_connections"]),
]
for column, (label, value) in zip(metric_columns, metrics):
    column.metric(label, value)

left_column, right_column = st.columns([1, 1])

with left_column:
    st.subheader("Recently registered cells")
    st.dataframe(load_recent_cells(10), use_container_width=True)

with right_column:
    st.subheader("Tracker slot occupancy")
    trackers = load_trackers()
    if not trackers:
        st.info("No trackers found.")
    for tracker_id, tracker_name in trackers:
        with st.expander(tracker_name, expanded=False):
            rows = tracker_status_snapshot(tracker_id)
            status_table = [
                {
                    "slot_code": row[0],
                    "is_connected": row[1],
                    "cell_name": row[2],
                    "mode_code": row[3],
                    "connected_since": row[4],
                }
                for row in rows
            ]
            st.dataframe(status_table, use_container_width=True)

st.info(
    "1. Registry -> register scientists, cells, groups\n"
    "2. Events -> connect cells to slots and associate sensors\n"
    "3. Events -> disconnect cells and dissociate sensors when done"
)

if st.button("Refresh"):
    st.cache_data.clear()
    st.rerun()
