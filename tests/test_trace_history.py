"""Trace browsing stays scoped and faithfully explains the stored execution."""

import json
from types import SimpleNamespace

import pytest

from src.rag.trace_history import (
    decode_trace_value, list_agent_traces, load_agent_trace, normalize_trace,
)


LOCATION = {"catalog_name": "catalog", "schema_name": "traces", "table_prefix": "project"}
TRACE_ID = "trace:/catalog.traces.project/abc123"


def encoded(value):
    return json.dumps(json.dumps(value))


def span(identifier, parent, name, kind="CHAIN", start=1_000_000_000, metadata=None):
    return {"span_id": identifier, "parent_span_id": parent, "name": name,
            "start_time_unix_nano": start, "end_time_unix_nano": start + 10_000_000,
            "status": {"code": "STATUS_CODE_OK", "message": ""},
            "attributes": {"mlflow.spanType": encoded(kind),
                           "mlflow.spanInputs": encoded({"query": "Actual question?"}),
                           "mlflow.spanOutputs": encoded({"answer": "Actual answer."}),
                           "metadata": encoded(metadata or {})}}


def trace(name="pdf_rag_answer"):
    return {
        "info": {"trace_id": TRACE_ID, "request_time": "2026-11-23T18:00:00Z", "state": "OK",
                 "execution_duration_ms": 30, "tags": {"mlflow.traceName": name},
                 "trace_location": {"type": "UC_TABLE_PREFIX", "uc_table_prefix": LOCATION},
                 "request_preview": encoded({"query": "Actual question?", "history": []}),
                 "response_preview": encoded({"answer": "Actual answer."})},
        "data": {"spans": [
            span("model", "plan", "DatabricksCompletions", "CHAT_MODEL", 1_002_000_000),
            span("plan", "graph", "plan", metadata={"langgraph_node": "plan", "langgraph_step": 1}),
            span("root", None, "pdf_rag_answer", "AGENT"),
            span("graph", "root", "LangGraph"),
        ]},
    }


def test_normalize_decodes_and_inherits_node_for_child_model_calls():
    result = normalize_trace(trace())
    model = next(item for item in result["spans"] if item["id"] == "model")
    assert model["type"] == "CHAT_MODEL"
    assert model["node_name"] == "plan" and model["graph_step"] == 1
    assert model["inputs"] == {"query": "Actual question?"}
    assert model["outputs"] == {"answer": "Actual answer."}
    assert model["status"] == "OK" and model["duration_ms"] == 10
    assert model["offset_ms"] == 2 and model["depth"] == 3
    assert result["question"] == "Actual question?" and result["answer"] == "Actual answer."
    assert result["tree"][0]["name"] == "pdf_rag_answer"
    assert [item["start_time_ms"] for item in result["spans"]] == sorted(item["start_time_ms"] for item in result["spans"])


def test_plain_text_and_json_empty_values_are_not_confused():
    assert decode_trace_value(encoded([])) == []
    assert decode_trace_value("ordinary text") == "ordinary text"
    assert decode_trace_value(encoded(False)) is False


class Client:
    def __init__(self, traces=None, loaded=None):
        self.traces = traces or []
        self.loaded = loaded or trace()
        self.search_kwargs = None
        self.loaded_ids = []

    def search_traces(self, **kwargs):
        self.search_kwargs = kwargs
        return self.traces

    def get_experiment(self, experiment_id):
        assert experiment_id == "123"
        return SimpleNamespace(trace_location=LOCATION)

    def get_trace(self, trace_id, display):
        assert display is False
        self.loaded_ids.append(trace_id)
        return self.loaded


def test_list_is_metadata_only_bounded_and_includes_evaluation_wrappers():
    client = Client(traces=[trace("DatabricksCompletions"), trace("predict_fn"), trace()])
    summaries = list_agent_traces("123", limit=50, lookback_hours=720, client=client)
    assert len(summaries) == 2
    assert summaries[0]["question"] == "Actual question?"
    assert client.search_kwargs["locations"] == ["123"]
    assert client.search_kwargs["include_spans"] is False
    assert client.search_kwargs["max_results"] == 100
    assert "trace.timestamp_ms >=" in client.search_kwargs["filter_string"]
    assert "trace.timestamp_ms <=" in client.search_kwargs["filter_string"]
    assert client.loaded_ids == []


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 51}, {"lookback_hours": 721}, {"lookback_hours": 0}])
def test_list_rejects_unbounded_search_inputs(kwargs):
    with pytest.raises(ValueError):
        list_agent_traces("123", client=Client(), **kwargs)


def test_uc_load_rejects_other_namespace_before_fetching_any_trace():
    client = Client()
    with pytest.raises(ValueError, match="configured experiment"):
        load_agent_trace("trace:/catalog.traces.other/abc", "123", client=client)
    assert client.loaded_ids == []


def test_load_verifies_actual_returned_membership_not_only_requested_id():
    outside = trace()
    outside["info"]["trace_location"]["uc_table_prefix"] = {**LOCATION, "table_prefix": "other"}
    with pytest.raises(ValueError, match="returned trace"):
        load_agent_trace(TRACE_ID, "123", client=Client(loaded=outside))
    mismatched_exp = trace()
    mismatched_exp["info"]["experiment_id"] = "999"
    with pytest.raises(ValueError, match="returned trace"):
        load_agent_trace(TRACE_ID, "123", client=Client(loaded=mismatched_exp))


def test_load_accepts_uc_metadata_without_experiment_id_and_nested_agent_wrapper():
    wrapped = trace("predict_fn")
    result = load_agent_trace(TRACE_ID, "123", client=Client(loaded=wrapped))
    assert result["summary"]["name"] == "predict_fn"
    assert result["question"] == "Actual question?"
    assert result["summary"]["span_count"] == 4


def test_event_objects_become_plain_json_and_cycles_do_not_create_recursive_trees():
    raw = trace()
    raw["data"]["spans"][0]["events"] = [SimpleNamespace(name="exception", timestamp=123,
                                                         attributes={"message": encoded("problem")})]
    raw["data"]["spans"][2]["parent_span_id"] = "graph"  # root -> graph -> root
    result = normalize_trace(raw)
    json.dumps(result)
    assert any(item.get("hierarchy_warning") for item in result["spans"])
    model = next(item for item in result["spans"] if item["id"] == "model")
    assert model["events"][0]["attributes"]["message"] == "problem"
