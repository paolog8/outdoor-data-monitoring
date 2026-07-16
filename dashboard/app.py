import streamlit as st

st.set_page_config(page_title="Outdoor PV Monitor", layout="wide")

# "wide" layout still leaves a capped max-width on the content container in
# recent Streamlit versions — stretch it to fill the browser window instead.
st.markdown(
    """
    <style>
    .block-container {
        max-width: 100%;
        padding-left: 2rem;
        padding-right: 2rem;
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
