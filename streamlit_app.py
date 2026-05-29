"""Entry point for the ORB backtester dashboard.

Run with:  streamlit run streamlit_app.py
Requires the UI extra:  pip install -e ".[ui]"
"""

from orb.webapp import main

main()
