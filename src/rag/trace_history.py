"""Read this application's saved agent activity from its configured MLflow experiment.

Listing reads bounded metadata only. Full span inputs/outputs are fetched only
when a caller explicitly loads one trace. These functions never run the agent.
"""

from __future__ import annotations

from datetime import datetime
import json
import time


GRAPH_NODES = {"plan", "search", "assess", "respond", "_route"}
AGENT_ROOT_NAMES = {"pdf_rag_answer", "predict_fn"}


def decode_trace_value(value):
    """UC span values may contain several layers of JSON string encoding."""
    for _ in range(6):
        if not isinstance(value, str):
            break
        try:
            decoded = json.loads(value)
        except (ValueError, TypeError):
            break
        if decoded == value:
            break
        value = decoded
    return value


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _enum(value):
    return str(getattr(value, "value", value) or "UNKNOWN").removeprefix("STATUS_CODE_")


def _milliseconds(value):
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            return None
    return None


def _payload(trace, which):
    data, info = _get(trace, "data", {}), _get(trace, "info", {})
    value = _get(data, "request" if which == "inputs" else "response")
    if value is None or value == "":
        value = _get(info, "request_preview" if which == "inputs" else "response_preview", "")
    return decode_trace_value(value)


def _text(payload, keys):
    payload = decode_trace_value(payload)
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), str):
                return payload[key]
        for key in ("inputs", "kwargs"):
            if key in payload:
                text = _text(payload[key], keys)
                if text:
                    return text
    return ""


def trace_summary(trace):
    info = _get(trace, "info", {})
    tags = _get(info, "tags", {}) or {}
    metadata = _get(info, "trace_metadata", {}) or {}
    stats = decode_trace_value(metadata.get("mlflow.trace.sizeStats", {}))
    return {
        "trace_id": _get(info, "trace_id", ""),
        "name": tags.get("mlflow.traceName", metadata.get("mlflow.traceName", "")),
        "request_time_ms": _milliseconds(_get(info, "request_time")),
        "duration_ms": _get(info, "execution_duration", _get(info, "execution_duration_ms")),
        "status": _enum(_get(info, "state", "UNKNOWN")),
        "question": _text(_payload(trace, "inputs"), ("query", "question")),
        "answer_preview": _text(_payload(trace, "outputs"), ("answer", "response"))[:500],
        "run_id": metadata.get("mlflow.sourceRun", metadata.get("mlflow.sourceRunId")),
        "span_count": stats.get("num_spans") if isinstance(stats, dict) else None,
    }


def _client(client):
    if client is None:
        from mlflow.tracking import MlflowClient
        return MlflowClient()
    return client


def _experiment_id(value):
    value = str(value)
    if not value.isdigit():
        raise ValueError("Use the application's configured numeric MLflow experiment ID.")
    return value


def list_agent_traces(experiment_id, *, limit=20, lookback_hours=168, client=None):
    """Return recent agent-run summaries from one experiment, never judge-only calls.

    Search is limited to one page of at most 100 metadata records and at most 30
    days. If model-judge traces crowd out older agent runs, shorten the time window
    or request a larger limit; this function does not silently scan more pages.
    """
    experiment_id = _experiment_id(experiment_id)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("Trace limit must be between 1 and 50.")
    if not isinstance(lookback_hours, (int, float)) or not 0 < lookback_hours <= 720:
        raise ValueError("Lookback must be greater than zero and at most 720 hours (30 days).")
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - int(lookback_hours * 3_600_000)
    traces = _client(client).search_traces(
        locations=[experiment_id],
        filter_string=f"trace.timestamp_ms >= {start_ms} AND trace.timestamp_ms <= {now_ms}",
        max_results=min(100, max(20, limit * 4)),
        order_by=["attributes.timestamp_ms DESC"], include_spans=False,
    )
    summaries = [trace_summary(trace) for trace in traces]
    summaries = [item for item in summaries if item["name"].lower() in AGENT_ROOT_NAMES]
    summaries.sort(key=lambda item: item["request_time_ms"] or 0, reverse=True)
    return summaries[:limit]


def _location_tuple(location):
    if location is None:
        return None
    for key in ("uc_table_prefix", "unity_catalog", "uc_schema"):
        child = _get(location, key)
        if child is not None:
            return _location_tuple(child)
    catalog, schema = _get(location, "catalog_name"), _get(location, "schema_name")
    if catalog and schema:
        return str(catalog), str(schema), _get(location, "table_prefix")
    return None


def _span_record(span):
    attributes = {key: decode_trace_value(value) for key, value in (_get(span, "attributes", {}) or {}).items()}
    metadata = decode_trace_value(attributes.get("metadata", {}))
    metadata = metadata if isinstance(metadata, dict) else {}
    name = _get(span, "name", "Unnamed step")
    start = _get(span, "start_time_ns", _get(span, "start_time_unix_nano"))
    end = _get(span, "end_time_ns", _get(span, "end_time_unix_nano"))
    start_ms, end_ms = (start / 1_000_000 if start is not None else None), (end / 1_000_000 if end is not None else None)
    status = _get(span, "status", {})
    return {
        "id": str(_get(span, "span_id", "")),
        "parent_id": _get(span, "parent_id", _get(span, "parent_span_id")),
        "name": name, "type": _enum(_get(span, "span_type", attributes.get("mlflow.spanType", "UNKNOWN"))),
        "start_time_ms": start_ms, "end_time_ms": end_ms,
        "duration_ms": max(0, end_ms - start_ms) if start_ms is not None and end_ms is not None else None,
        "offset_ms": None,
        "status": _enum(_get(status, "status_code", _get(status, "code", "UNKNOWN"))),
        "status_message": _get(status, "description", _get(status, "message", "")),
        "inputs": decode_trace_value(_get(span, "inputs", attributes.get("mlflow.spanInputs"))),
        "outputs": decode_trace_value(_get(span, "outputs", attributes.get("mlflow.spanOutputs"))),
        "attributes": attributes,
        "node_name": metadata.get("langgraph_node", name if name in GRAPH_NODES else None),
        "graph_step": metadata.get("langgraph_step"),
        "events": [
            {
                "name": _get(event, "name", ""),
                "timestamp": _get(event, "timestamp", _get(event, "time_unix_nano")),
                "attributes": {key: decode_trace_value(value) for key, value in
                               (_get(event, "attributes", {}) or {}).items()},
            }
            for event in (_get(span, "events", []) or [])
        ],
    }


def normalize_trace(trace):
    """Build flat chronological steps and a nested tree from actual span parents."""
    summary = trace_summary(trace)
    spans = [_span_record(span) for span in _get(_get(trace, "data", {}), "spans", [])]
    spans.sort(key=lambda span: (span["start_time_ms"] or 0, span["id"]))
    lookup = {span["id"]: span for span in spans}
    origin = min((span["start_time_ms"] for span in spans if span["start_time_ms"] is not None), default=None)
    tree_nodes = {span["id"]: {**span, "children": []} for span in spans}
    roots = []
    for span in spans:
        ancestors, parent_id = [], span["parent_id"]
        seen = {span["id"]}
        while parent_id in lookup and parent_id not in seen:
            seen.add(parent_id)
            parent = lookup[parent_id]
            ancestors.append(parent)
            parent_id = parent["parent_id"]
        if parent_id in seen:
            span["parent_id"] = None
            span["hierarchy_warning"] = "A cyclic parent link was detached."
            ancestors = []
        span["depth"] = len(ancestors)
        span["offset_ms"] = span["start_time_ms"] - origin if origin is not None and span["start_time_ms"] is not None else None
        if not span["node_name"]:
            span["node_name"] = next((parent["node_name"] for parent in ancestors if parent["node_name"]), None)
        if span["graph_step"] is None:
            span["graph_step"] = next((parent["graph_step"] for parent in ancestors if parent["graph_step"] is not None), None)
        node = tree_nodes[span["id"]]
        node.update(span)
        if span["parent_id"] in tree_nodes:
            tree_nodes[span["parent_id"]]["children"].append(node)
        else:
            roots.append(node)
    inputs, outputs = _payload(trace, "inputs"), _payload(trace, "outputs")
    # A wrapper's preview may be truncated. Prefer the actual agent boundary I/O.
    agent = next((span for span in spans if span["name"] == "pdf_rag_answer"), None)
    if agent:
        inputs, outputs = agent["inputs"], agent["outputs"]
    question, answer = _text(inputs, ("query", "question")), _text(outputs, ("answer", "response"))
    summary.update({"span_count": len(spans), "question": question or summary["question"],
                    "answer_preview": (answer or summary["answer_preview"])[:500]})
    return {"summary": summary, "spans": spans, "tree": roots,
            "inputs": inputs, "outputs": outputs, "question": summary["question"], "answer": answer}


def load_agent_trace(trace_id, experiment_id, *, client=None):
    """Load one selected trace and verify it belongs to the configured experiment."""
    experiment_id = _experiment_id(experiment_id)
    client = _client(client)
    experiment = client.get_experiment(experiment_id)
    expected_location = _location_tuple(_get(experiment, "trace_location"))
    trace_id = str(trace_id)
    if expected_location:
        namespace, separator, opaque_id = trace_id.removeprefix("trace:/").partition("/")
        allowed_namespace = ".".join(part for part in expected_location if part)
        if not trace_id.startswith("trace:/") or not separator or not opaque_id or "/" in opaque_id or namespace != allowed_namespace:
            raise ValueError("Choose a trace from this application's configured experiment.")
    trace = client.get_trace(trace_id, display=False)
    info = _get(trace, "info", {})
    actual_experiment = _get(info, "experiment_id")
    actual_location = _location_tuple(_get(info, "trace_location"))
    if actual_experiment is not None:
        belongs = str(actual_experiment) == experiment_id
    else:
        belongs = bool(expected_location and actual_location == expected_location)
    if not belongs:
        raise ValueError("The returned trace does not belong to this application's configured experiment.")
    normalized = normalize_trace(trace)
    if not any(span["name"] == "pdf_rag_answer" for span in normalized["spans"]):
        raise ValueError("This trace contains no PDF RAG agent execution.")
    return normalized
