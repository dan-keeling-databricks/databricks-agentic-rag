"""Start Streamlit on the port assigned by Databricks Apps (8000 locally)."""

import os
import sys

if __name__ == "__main__":
    os.execv(sys.executable, [
        sys.executable, "-m", "streamlit", "run", "app.py",
        "--server.address", "0.0.0.0",
        "--server.port", os.getenv("DATABRICKS_APP_PORT", "8000"),
        "--server.headless", "true",
    ])
