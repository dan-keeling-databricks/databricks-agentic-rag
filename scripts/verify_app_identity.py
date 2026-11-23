"""Temporary deployment diagnostic: test the app identity, then start Streamlit.

Run only as a temporary Databricks Apps command during deployment verification.
The normal app startup is run_app.py and never runs this diagnostic.
"""

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from databricks.sdk import WorkspaceClient
import mlflow

from src.rag.agent import RagAgent, configure_tracing
from src.rag.config import Settings


def main():
    try:
        workspace = WorkspaceClient()
        identity = workspace.current_user.me()
        settings = Settings.from_env()
        configure_tracing(settings)
        result = RagAgent(settings, workspace_client=workspace).answer(
            "According to A Compact Guide to Large Language Models, "
            "what are large language models designed to do?"
        )
        summary = {
            "identity_id": identity.id,
            "identity_name": identity.user_name,
            "trace_id": result.get("trace_id"),
            "search_count": result["search_count"],
            "answer": result["answer"],
            "sources": [{k: item[k] for k in ("filename", "page_start", "page_end", "chunk_id")}
                        for item in result["sources"]],
        }
        Path("/tmp/app-identity-check.json").write_text(json.dumps(summary, indent=2))
        print("APP_IDENTITY_CHECK RESULT " + json.dumps(summary), flush=True)
        assert summary["trace_id"], "No agent trace ID was captured."
        assert summary["sources"], "The agent did not return cited source passages."
        assert 1 <= summary["search_count"] <= settings.max_searches, "Search bound failed."
        mlflow.flush_trace_async_logging()
        print("APP_IDENTITY_CHECK SUCCESS", flush=True)
    except Exception as error:
        print("APP_IDENTITY_CHECK FAILED " + json.dumps({
            "error_type": type(error).__name__, "message": str(error),
        }), flush=True)
        raise SystemExit(1) from error
    os.chdir(ROOT)
    os.execv(sys.executable, [sys.executable, str(ROOT / "run_app.py")])


if __name__ == "__main__":
    main()
