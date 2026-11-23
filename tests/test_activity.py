"""The history viewer reads saved operations, without running a new answer."""

from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from src.rag import activity
from src.rag.agent import RagAgent
from src.rag.config import Settings

APP = Path(__file__).parents[1] / "app.py"


def configured(monkeypatch):
    monkeypatch.setenv("AGENT_ENDPOINT", "catalog.rag.model")
    monkeypatch.setenv("VECTOR_SEARCH_INDEX", "catalog.rag.search")
    monkeypatch.setenv("MLFLOW_EXPERIMENT_ID", "123")
    monkeypatch.setenv("DATABRICKS_HOST", "workspace.example")


def compiled():
    return RagAgent(Settings("model", "catalog.rag.index"), workspace_client=object(),
                    model_client=object(), retriever=object()).graph


def saved_trace(trace_id="trace-one"):
    summary = {"trace_id": trace_id, "request_time_ms": 1795450000000, "duration_ms": 2000,
               "status": "OK", "question": "What does Auto Loader do?", "answer_preview": "Reads new files."}
    spans = [
        {"id": "root", "parent_id": None, "name": "pdf_rag_answer", "type": "AGENT", "status": "OK",
         "node_name": None, "offset_ms": 0, "duration_ms": 2000,
         "inputs": {"query": summary["question"]}, "outputs": {"answer": "Reads new files."}},
        {"id": "plan", "parent_id": "root", "name": "plan", "type": "CHAIN", "status": "OK",
         "node_name": "plan", "offset_ms": 100, "duration_ms": 400,
         "inputs": {"question": summary["question"]}, "outputs": {"search_query": "Auto Loader ingestion"}},
        {"id": "assess", "parent_id": "root", "name": "assess", "type": "CHAIN", "status": "OK",
         "node_name": "assess", "offset_ms": 1000, "duration_ms": 400,
         "inputs": {"documents": [{"content": "A PDF passage"}]}, "outputs": {"sufficient": True}},
    ]
    return {"summary": summary, "spans": spans, "tree": [], "answer": "Reads new files."}


def test_diagram_uses_compiled_langgraph_and_preserves_conditional_loop():
    graph = activity.graph_definition(compiled())
    dot = activity.topology_dot(graph, saved_trace()["spans"], "assess")
    assert set(graph["nodes"]) == {"__start__", "plan", "search", "assess", "respond", "__end__"}
    assert '"assess" -> "search" [style=dashed' in dot
    assert '"assess" -> "respond" [style=dashed' in dot
    assert '1 recorded visit(s)' in dot
    assert 'fillcolor="#fed7aa"' in dot


def test_activity_load_select_step_and_filter_do_not_rerun_inference(monkeypatch):
    configured(monkeypatch)
    calls = {"list": 0, "load": 0}
    trace = saved_trace()
    monkeypatch.setattr(activity, "get_agent", lambda: SimpleNamespace(graph=compiled()))
    def listing(*args, **kwargs):
        calls["list"] += 1
        assert args == ("123",)
        return [trace["summary"]]
    def loading(*args):
        calls["load"] += 1
        assert args == ("trace-one", "123")
        return trace
    monkeypatch.setattr(activity, "list_agent_traces", listing)
    monkeypatch.setattr(activity, "load_agent_trace", loading)
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert calls == {"list": 0, "load": 0}  # Chat renders without history requests.
    app.button(key="load_activity").click().run()
    assert not app.exception
    assert calls == {"list": 1, "load": 1}
    step = next(item for item in app.selectbox if item.label == "Inspect a step")
    step.select(1).run()
    assert not app.exception
    assert any("Auto Loader ingestion" in item.value for item in app.markdown)
    assert calls == {"list": 1, "load": 1}  # A saved step needs no extra fetch.
    next(item for item in app.text_input if item.label == "Filter loaded requests").set_value("no match").run()
    assert not app.exception
    assert any("No loaded questions match" in item.value for item in app.info)


def test_empty_history_and_backend_errors_leave_chat_available(monkeypatch):
    configured(monkeypatch)
    monkeypatch.setattr(activity, "get_agent", lambda: SimpleNamespace(graph=compiled()))
    monkeypatch.setattr(activity, "list_agent_traces", lambda *a, **kw: [])
    app = AppTest.from_file(str(APP)).run()
    app.button(key="load_activity").click().run()
    assert not app.exception
    assert any("No recorded agent requests" in item.value for item in app.info)
    def denied(*args, **kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(activity, "list_agent_traces", denied)
    app.button(key="load_activity").click().run()
    assert not app.exception
    assert "History could not be loaded" in app.error[0].value
    assert app.chat_input[0].placeholder == "Ask a question about your PDFs"


def test_recorded_graph_escapes_external_span_labels_and_keeps_parent_links():
    spans = saved_trace()["spans"]
    spans[1]["name"] = 'unsafe"; node [label="example'
    dot = activity.execution_dot(spans, "plan")
    assert '"root" -> "plan";' in dot
    assert r'unsafe\"; node' in dot
    assert '·' in dot
    assert r'\u00b7' not in dot


def test_failed_reload_clears_previous_history_and_details(monkeypatch):
    configured(monkeypatch)
    trace = saved_trace()
    monkeypatch.setattr(activity, "get_agent", lambda: SimpleNamespace(graph=compiled()))
    monkeypatch.setattr(activity, "list_agent_traces", lambda *a, **kw: [trace["summary"]])
    monkeypatch.setattr(activity, "load_agent_trace", lambda *a: trace)
    app = AppTest.from_file(str(APP)).run()
    app.button(key="load_activity").click().run()
    assert any(item.label == "Previous request" for item in app.selectbox)
    next(item for item in app.selectbox if item.label == "History window").select(24).run()
    assert any("preceding 7 day(s)" in item.value for item in app.caption)
    def failed(*args, **kwargs):
        raise PermissionError("denied")
    monkeypatch.setattr(activity, "list_agent_traces", failed)
    app.button(key="load_activity").click().run()
    assert not app.exception
    assert not any(item.label == "Previous request" for item in app.selectbox)
    assert any("graph is available, but history could not be read" in item.value for item in app.info)
