import streamlit as st

st.set_page_config(page_title="Outdoor PV Monitor", layout="wide")

pg = st.navigation(
    [
        st.Page("pages/overview.py", title="Overview", default=True),
        st.Page("pages/1_Events.py", title="Events"),
        st.Page("pages/2_Registry.py", title="Registry"),
    ]
)
pg.run()
