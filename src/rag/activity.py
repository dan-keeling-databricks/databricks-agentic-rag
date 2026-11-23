"""Read-only Streamlit view of the compiled graph and recorded MLflow steps."""

from collections import Counter
from datetime import datetime, timezone
import json
import logging
import os

import streamlit as st

from .agent import get_agent
from .links import trace_url
from .trace_history import list_agent_traces, load_agent_trace

STEP_LABELS = {
    "__start__": "Question", "plan": "Plan the search", "search": "Search the PDFs",
    "assess": "Check the evidence", "respond": "Write the answer", "__end__": "Finished",
}


def dot_string(value):
    return json.dumps(value, ensure_ascii=False)


def graph_definition(compiled):
    """Read topology from LangGraph itself; never maintain a second flowchart."""
    graph = compiled.get_graph()
    return {"nodes": list(graph.nodes), "edges": [
        {"source": edge.source, "target": edge.target, "conditional": edge.conditional}
        for edge in graph.edges
    ]}


def topology_dot(graph, spans=(), selected_node=None):
    counts = Counter(item.get("node_name") for item in spans
                     if item.get("name") in STEP_LABELS)
    lines = ['digraph { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#f3f4f6"];']
    for node in graph["nodes"]:
        label = STEP_LABELS.get(node, node)
        if counts[node]:
            label += f"\n{counts[node]} recorded visit(s)"
        color = "#fed7aa" if node == selected_node else "#bbf7d0" if counts[node] else "#f3f4f6"
        lines.append(f'{dot_string(node)} [label={dot_string(label)}, fillcolor={dot_string(color)}];')
    for edge in graph["edges"]:
        label = ""
        if edge["conditional"]:
            label = ' [style=dashed, label="refine search"]' if edge["target"] == "search" else ' [style=dashed, label="enough evidence / stop"]'
        lines.append(f'{dot_string(edge["source"])} -> {dot_string(edge["target"])}{label};')
    return "\n".join(lines + ["}"])


def execution_dot(spans, selected_id):
    """Parent-child links show nesting; start times determine the step numbers."""
    lines = ['digraph { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#eff6ff"];']
    ids = {span["id"] for span in spans}
    for number, span in enumerate(spans, 1):
        duration = span.get("duration_ms")
        timing = f"{duration / 1000:.2f}s" if duration is not None else "in progress"
        label = f'{number}. {span["name"]}\n{span["type"]} · {timing}'
        color = "#fecaca" if "ERROR" in span["status"] else "#fed7aa" if span["id"] == selected_id else "#eff6ff"
        lines.append(f'{dot_string(span["id"])} [label={dot_string(label)}, fillcolor={dot_string(color)}];')
        if span.get("parent_id") in ids:
            lines.append(f'{dot_string(span["parent_id"])} -> {dot_string(span["id"])};')
    return "\n".join(lines + ["}"])


def timestamp(value):
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).strftime("%d %b %Y %H:%M:%S UTC") if value else "Time unavailable"


def describe_step(span):
    """Explain saved operational decisions, without inventing model reasoning."""
    output = span.get("outputs")
    if not isinstance(output, dict):
        return
    if span.get("node_name") == "plan" and output.get("search_query"):
        st.write("Search query:", output["search_query"])
    elif span.get("node_name") == "assess" and "sufficient" in output:
        st.write("Evidence considered sufficient:", "Yes" if output["sufficient"] else "No")
        if output.get("search_query"):
            st.write("Next search query:", output["search_query"])
    elif span.get("node_name") == "search":
        st.write(f'Search number: {output.get("search_count", "not recorded")} · Passages kept: {len(output.get("documents", []))}')
    if output.get("answer"):
        st.text(output["answer"])


def render_activity(settings):
    st.subheader("Follow the agent from question to answer")
    st.write("Explore the LangGraph flow, then choose a previous request to see the steps that actually ran. Loading history does not ask the model a new question.")
    st.info("Shared history: everyone authorized to use this app can inspect this deployment's saved questions, answers, and document passages, including other users' requests.")
    st.caption("This shows recorded operations and decisions, not the model's private internal reasoning. Recent requests can take a moment to appear in MLflow.")
    window = st.selectbox("History window", [24, 168, 720], format_func=lambda n: {24: "Last 24 hours", 168: "Last 7 days", 720: "Last 30 days"}[n], index=1)
    if st.button("Load graph and recent runs", key="load_activity"):
        st.session_state.pop("activity_traces", None)
        st.session_state.pop("activity_detail", None)
        st.session_state.activity_error = False
        try:
            with st.spinner("Reading the agent graph and recent MLflow requests…"):
                # Initializing clients and inspecting topology makes no model call.
                agent = get_agent()
                st.session_state.activity_graph = graph_definition(agent.graph)
                st.session_state.activity_traces = list_agent_traces(settings.mlflow_experiment_id, limit=30, lookback_hours=window)
                st.session_state.activity_loaded_window = window
                st.session_state.activity_loaded_at = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        except Exception:
            st.session_state.activity_error = True
            logging.exception("Agent activity history could not be loaded")
            st.error("History could not be loaded. Check the app's MLflow experiment and trace-warehouse access, then retry.")
    graph = st.session_state.get("activity_graph")
    traces = st.session_state.get("activity_traces", [])
    if not graph:
        st.caption("Select Load graph and recent runs to begin.")
        return
    if not traces:
        st.graphviz_chart(topology_dot(graph))
        if st.session_state.get("activity_error"):
            st.info("The graph is available, but history could not be read. Load again to retry.")
        else:
            st.info("No recorded agent requests were found in the loaded window. Ask a question in Chat, wait briefly, and load history again.")
        return
    applied = st.session_state.get("activity_loaded_window", window)
    loaded_at = st.session_state.get("activity_loaded_at", "unknown time")
    st.caption(f"History loaded at {loaded_at} for the preceding {applied // 24} day(s). Choose Load graph and recent runs to apply a different window.")
    term = st.text_input("Filter loaded requests", placeholder="Words from the question")
    visible = [row for row in traces if term.casefold() in row.get("question", "").casefold()]
    st.caption(f"Showing {len(visible)} of {len(traces)} loaded requests. Checks up to 100 recent trace records and displays up to 30 agent requests. Reload to refresh or change the window.")
    if not visible:
        st.graphviz_chart(topology_dot(graph))
        st.info("No loaded questions match that filter.")
        return
    by_id = {row["trace_id"]: row for row in visible}
    selected = st.selectbox("Previous request", list(by_id), format_func=lambda key: f'{timestamp(by_id[key]["request_time_ms"])} · {by_id[key]["status"]} · {by_id[key]["question"][:140]}')
    try:
        saved = st.session_state.get("activity_detail")
        if not saved or saved["summary"]["trace_id"] != selected:
            with st.spinner("Loading the recorded steps…"):
                saved = load_agent_trace(selected, settings.mlflow_experiment_id)
                st.session_state.activity_detail = saved
    except Exception:
        logging.exception("Agent activity trace could not be loaded")
        st.graphviz_chart(topology_dot(graph))
        st.error("This request's details could not be read. It may still be saving, or its trace data may no longer be available. Reload history to retry.")
        return
    summary, spans = saved["summary"], saved["spans"]
    st.markdown("**Question**")
    st.text(summary.get("question", ""))
    duration = summary.get("duration_ms")
    st.caption(f'{timestamp(summary.get("request_time_ms"))} · {summary["status"]}' + (f" · {duration / 1000:.2f} seconds" if duration is not None else ""))
    link = trace_url(os.getenv("DATABRICKS_HOST", ""), settings.mlflow_experiment_id, selected)
    if link:
        st.link_button("Open this request in MLflow", link)
    if saved.get("answer"):
        with st.expander("Saved answer"):
            st.text(saved["answer"])
    if not spans:
        st.graphviz_chart(topology_dot(graph))
        st.info("The trace has no saved steps yet.")
        return
    index = st.selectbox("Inspect a step", range(len(spans)), format_func=lambda i: f'{i + 1}. {spans[i]["name"]} · {spans[i]["type"]}')
    span = spans[index]
    left, right = st.columns(2)
    with left:
        st.markdown("**LangGraph flow**")
        selected_node = "assess" if span.get("node_name") == "_route" else span.get("node_name")
        st.graphviz_chart(topology_dot(graph, spans, selected_node))
        st.caption("Current deployed graph. Green nodes were visited; orange marks the selected step. Dashed arrows are decisions. Historical runs may use an older graph definition.")
    with right:
        st.markdown("**Recorded operations**")
        st.graphviz_chart(execution_dot(spans, span["id"]))
        st.caption("Numbers follow start time. Lines link a parent operation to its child; overlapping steps are not added together. Orange is selected; red indicates an error.")
    st.dataframe([{"Step": i + 1, "Operation": row["name"], "Kind": row["type"],
                   "Start (seconds)": round(row["offset_ms"] / 1000, 3) if row.get("offset_ms") is not None else None,
                   "Duration (seconds)": round(row["duration_ms"] / 1000, 3) if row.get("duration_ms") is not None else None,
                   "Status": row["status"]} for i, row in enumerate(spans)], hide_index=True)
    st.markdown(f'**Step {index + 1}: {span["name"]}**')
    describe_step(span)
    for label, field in [("Inputs — what this step received", "inputs"), ("Outputs — what this step produced", "outputs")]:
        with st.expander(label, expanded=True):
            if span.get(field) is None:
                st.caption("Not recorded for this step.")
            else:
                st.json(span[field], expanded=False)
    with st.expander("Step metadata and errors"):
        st.json({key: span.get(key) for key in ("id", "parent_id", "node_name", "status", "status_message", "attributes", "events")}, expanded=False)
    st.caption("Inputs and outputs may contain complete source passages and prompts. The saved final response is in the respond step and the top-level agent output.")
