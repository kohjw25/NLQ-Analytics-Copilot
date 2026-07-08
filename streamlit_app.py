"""Deployment entrypoint for the Insight Copilot Streamlit app.

Hosting platforms (Streamlit Community Cloud, containers, etc.) run
`streamlit run streamlit_app.py`. This shim guarantees the repository root is on
the Python path so the `insight_copilot` package imports cleanly, then loads the
app module (which renders the UI on import).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import insight_copilot.app  # noqa: E402,F401  (renders the app on import)
