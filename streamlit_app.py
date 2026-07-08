"""Deployment entrypoint for the Insight Copilot Streamlit app.

Hosting platforms (Streamlit Community Cloud, containers, etc.) run
`streamlit run streamlit_app.py`. This shim guarantees the repository root is on
the Python path so the `insight_copilot` package imports cleanly, then calls the
app's render function.

Streamlit re-executes this file on every interaction, so we must *call* run()
each time — importing the app module for its side effects would only render on
the first load and then blank on every rerun (the module is cached after the
first import).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from insight_copilot.app import run  # noqa: E402

run()
