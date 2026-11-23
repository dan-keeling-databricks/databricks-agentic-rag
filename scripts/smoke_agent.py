"""Ask the live agent a question and verify its persisted MLflow trace.

The trace ID is saved before readback. A watchdog terminates this process if
flush/readback exceeds 60 seconds; it does not leave a background read running.
Run only after the ingestion job and search index have finished updating.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def trace_browser_url(host: str, experiment_id: str, trace_id: str) -> str:
    """Qualified UC trace IDs retain their full value for SDK calls only."""
    browser_id = trace_id.rsplit("/", 1)[-1] if trace_id.startswith("trace:/") else trace_id
    return f"{host.rstrip('/')}/ml/experiments/{experiment_id}/traces/{browser_id}"


def check_trace(trace, query: str, start_ms: int, end_ms: int) -> dict:
    if trace is None:
        raise RuntimeError("MLflow did not return the saved application trace.")
    if not start_ms <= trace.info.request_time <= end_ms:
        raise RuntimeError("The saved trace timestamp does not match this application request.")
    if query not in json.dumps(trace.data.request, ensure_ascii=False, default=str):
        raise RuntimeError("The persisted trace does not contain this application question.")
    spans = trace.data.spans
    if not spans:
        raise RuntimeError("The persisted application trace has no spans.")
    span_types = {str(span.span_type) for span in spans}
    if "AGENT" not in span_types:
        raise RuntimeError("The application boundary AGENT span is missing.")
    retrieval = [span for span in spans if str(span.span_type) == "RETRIEVER"]
    models = [span for span in spans if str(span.span_type) in {"CHAT_MODEL", "LLM"}]
    graph = [span for span in spans if str(span.span_type) == "CHAIN"]
    if not retrieval or not any(span.outputs for span in retrieval):
        raise RuntimeError("A persisted retrieval span with retrieved evidence is missing.")
    if not models or not all(span.inputs and span.outputs for span in models):
        raise RuntimeError("Persisted model spans with request/response content are missing.")
    if not graph:
        raise RuntimeError("Persisted LangGraph CHAIN spans are missing.")
    return {"span_count": len(spans), "span_types": sorted(span_types),
            "retrieval_spans": len(retrieval), "model_spans": len(models),
            "graph_spans": len(graph)}


def ask_and_verify(agent, mlflow, workspace, settings, query, history, output: Path, name: str):
    start_ms = int(time.time() * 1000)
    result = agent.answer(query=query, history=history)
    end_ms = int(time.time() * 1000)
    trace_id = result.get("trace_id") or mlflow.get_last_active_trace_id()
    saved = {"trace_id": trace_id, "query": query, "request_start_ms": start_ms,
             "request_end_ms": end_ms, "verified": False}
    trace_file = output / f"{name}.json"
    trace_file.write_text(json.dumps(saved, indent=2))
    print(f"Saved application trace ID: {trace_id} ({trace_file})", flush=True)
    if not trace_id:
        raise RuntimeError("The agent returned no trace ID. The request will not be repeated to recover it.")

    def deadline_expired():
        failure = {**saved, "error": "Trace flush/readback exceeded the 60-second process deadline."}
        (output / f"{name}-readback-error.json").write_text(json.dumps(failure, indent=2))
        print(failure["error"] + f" Saved trace ID: {trace_id}", file=sys.stderr, flush=True)
        os._exit(124)

    watchdog = threading.Timer(60, deadline_expired)
    watchdog.daemon = True
    watchdog.start()
    try:
        mlflow.flush_trace_async_logging()
        trace = mlflow.get_trace(trace_id)
        observed = check_trace(trace, query, start_ms, end_ms)
        experiment = mlflow.get_experiment(settings.mlflow_experiment_id)
        location = getattr(experiment, "trace_location", None)
        location = location.to_dict() if hasattr(location, "to_dict") else str(location)
    except Exception as error:
        (output / f"{name}-readback-error.json").write_text(
            json.dumps({**saved, "error": str(error)}, indent=2))
        raise
    finally:
        watchdog.cancel()

    if not 1 <= result["search_count"] <= settings.max_searches:
        raise RuntimeError("The agent did not respect its configured search-call bound.")
    if not result.get("sources"):
        raise RuntimeError("The answerable smoke-test question produced no cited sources.")
    summary = {**saved, "verified": True, **observed,
               "trace_location": location, "source_count": len(result["sources"]),
               "search_count": result["search_count"], "answer": result["answer"],
               "trace_url": trace_browser_url(workspace.config.host, settings.mlflow_experiment_id, trace_id)}
    trace_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["profile", "experiment-id", "index", "agent-endpoint"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--warehouse-id", help="Warehouse used for UC trace readback.")
    parser.add_argument("--output-dir", default=str(ROOT / "tmp" / "smoke"))
    parser.add_argument("--followup", action="store_true", help="Also ask and verify a follow-up in the same chat scenario.")
    args = parser.parse_args(argv)

    os.environ["DATABRICKS_CONFIG_PROFILE"] = args.profile
    os.environ["MLFLOW_TRACKING_URI"] = f"databricks://{args.profile}"
    if args.warehouse_id:
        os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = args.warehouse_id
    import mlflow
    from databricks.sdk import WorkspaceClient
    from src.rag.agent import RagAgent, configure_tracing
    from src.rag.config import Settings

    settings = Settings(agent_endpoint=args.agent_endpoint, vector_search_index=args.index,
                        mlflow_experiment_id=args.experiment_id, use_ai_gateway=True)
    configure_tracing(settings)
    workspace = WorkspaceClient(profile=args.profile)
    agent = RagAgent(settings, workspace_client=workspace)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    query = "According to A Compact Guide to Large Language Models, what is an LLM and what does it do?"
    first = ask_and_verify(agent, mlflow, workspace, settings, query, [], output, "first-question")
    if args.followup:
        history = [{"role": "user", "content": query}, {"role": "assistant", "content": first["answer"]}]
        ask_and_verify(agent, mlflow, workspace, settings,
                       "What warning does the same guide give about using its responses as factual references?",
                       history, output, "follow-up")


if __name__ == "__main__":
    main()
