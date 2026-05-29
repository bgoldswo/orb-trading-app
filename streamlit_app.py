"""Entry point for the ORB app (multipage: Backtest + Paper signals).

Run with:  streamlit run streamlit_app.py
Requires the UI extra:  pip install -e ".[ui]"
"""

import streamlit as st

from orb.webapp import backtest_page, optimizer_page, signals_page

st.set_page_config(page_title="ORB Backtester", page_icon="📈", layout="wide")

pages = [
    st.Page(backtest_page, title="Backtest", icon="📈", default=True),
    st.Page(optimizer_page, title="Optimizer", icon="🧪"),
    st.Page(signals_page, title="Paper signals", icon="📡"),
]
st.navigation(pages).run()
