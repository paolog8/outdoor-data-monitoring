import streamlit as st

st.set_page_config(page_title="Outdoor PV Monitor", layout="wide")

# "wide" layout still leaves a capped max-width on the content container in
# recent Streamlit versions — stretch it to fill the browser window instead.
st.markdown(
    """
    <style>
    [data-testid="stMainBlockContainer"],
    [data-testid="block-container"],
    .block-container {
        max-width: 100% !important;
        padding-left: 2rem !important;
        padding-right: 2rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

pg = st.navigation(
    [
        st.Page("pages/overview.py", title="Overview", default=True),
        st.Page("pages/1_Events.py", title="Events"),
        st.Page("pages/2_Registry.py", title="Registry"),
    ]
)
pg.run()
