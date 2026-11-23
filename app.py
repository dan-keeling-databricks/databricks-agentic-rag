"""Streamlit interface: ask questions and understand the deployed solution."""

import logging
import os

import streamlit as st

from src.rag.activity import render_activity
from src.rag.agent import get_agent
from src.rag.config import Settings
from src.rag.links import architecture_links, trace_url

st.set_page_config(page_title="Ask your PDFs", page_icon="📚", layout="wide")
st.title("Ask your PDFs")
st.caption("Find answers in your document collection, with references you can check.")

try:
    settings = Settings.from_env()
except (ValueError, TypeError) as error:
    st.error(f"This app needs deployment configuration: {error}")
    st.info("Follow the deployment quickstart in the repository, then restart the app.")
    st.stop()

chat_tab, activity_tab, architecture_tab = st.tabs(["Chat", "Agent activity", "Architecture"])


def show_answer(result):
    st.markdown(result["answer"])
    st.caption("AI-generated answer — check the cited passages before relying on it.")
    sources = result.get("sources", [])
    if sources:
        with st.expander(f"Read the supporting passages ({len(sources)})"):
            for item in sources:
                pages = str(item["page_start"])
                if item["page_end"] != item["page_start"]:
                    pages += f"–{item['page_end']}"
                st.markdown(f"**{item['filename']} · PDF page {pages}**")
                st.text(item["content"])
                st.caption(item.get("source_path", ""))
    st.caption(f"{result.get('search_count', 0)} searches · {result.get('latency_seconds', 0):.1f} seconds")
    host = os.getenv("DATABRICKS_HOST", "")
    link = trace_url(host, settings.mlflow_experiment_id, result.get("trace_id"))
    if link:
        st.link_button("Inspect this request in MLflow", link)


with chat_tab:
    st.info("Everyone authorized to use this app searches the same collection. Searches run using the app's service identity.")
    st.caption("Follow-up questions use this browser session's conversation. Clear chat to start a new topic. PDF page numbers count from the first page of the file.")
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if st.button("Clear chat", disabled=not st.session_state.messages):
        st.session_state.messages = []
        st.rerun()
    if not st.session_state.messages:
        st.markdown("**Try a question**")
        st.markdown("What does the ingestion ebook say about Auto Loader?\n\nHow are digital twins used in manufacturing?")
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                show_answer(message["result"])
            else:
                st.markdown(message["content"])
    question = st.chat_input("Ask a question about your PDFs", max_chars=12000)
    if question:
        history = [{"role": item["role"], "content": item["content"]} for item in st.session_state.messages]
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            try:
                with st.status("Searching the documents and checking the evidence…", expanded=True) as status:
                    st.write(f"The agent may refine its search, up to {settings.max_searches} times, before answering.")
                    result = get_agent().answer(question, history=history)
                    status.update(label="Finished checking the evidence", state="complete", expanded=False)
                show_answer(result)
                st.session_state.messages.extend([
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": result["answer"], "result": result},
                ])
            except Exception:
                logging.exception("Document question failed")
                st.error("The request could not be completed. Check that ingestion and index synchronization have finished and that the app can access the model, index, and MLflow experiment.")
                st.info("The Architecture tab links to the deployed components. Check the app logs for technical details, then retry.")

with activity_tab:
    render_activity(settings)


with architecture_tab:
    st.subheader("How a PDF becomes a cited answer")
    st.markdown("""
1. **Land the PDFs.** Upload files into a governed Databricks volume: a folder where Databricks manages access.
2. **Pick up new files.** Run the ingestion job. Auto Loader remembers which files it has already seen.
3. **Read and prepare them.** The Lakeflow pipeline uses `ai_parse_document` to read PDF content, `ai_extract` to capture a title, summary and topics, and `ai_prep_search` to create useful passages for search. Intermediate results and processing errors are stored in Delta tables.
4. **Update the search index.** Databricks AI Search creates numerical representations of the passages and synchronizes the index after the pipeline finishes. Search combines meaning with matching words.
5. **Answer a question.** A LangGraph agent searches, checks the evidence, and can refine its search. It answers only when evidence is sufficient, attaching document and page references.
6. **Measure and inspect.** MLflow records requests, model calls and retrieved passages. Its managed dataset holds benchmark questions and reference answers, and its registered scorers define the AI and code checks. An evaluation notebook asks the same agent those questions and saves the results in the experiment.
""")
    st.graphviz_chart('''digraph {
      rankdir=LR;
      node [shape=box, style="rounded"];
      PDFs -> "UC volume" -> "Auto Loader" -> "Parse / extract / prepare" -> "Delta chunks" -> "AI Search";
      "Your question" -> "LangGraph agent";
      "LangGraph agent" -> "AI Search" [label="search / refine"];
      "LangGraph agent" -> "Cited answer";
      "LangGraph agent" -> "MLflow traces";
      "MLflow dataset + registered scorers" -> "Evaluation notebook" -> "MLflow results";
    }''')
    st.subheader("Open the deployed components")
    host = os.getenv("DATABRICKS_HOST", "")
    if host:
        for label, url in architecture_links(host, settings).items():
            st.link_button(label, url)
    else:
        st.info("Component links appear when DATABRICKS_HOST is configured by Databricks Apps or your local environment.")
    st.caption("Databricks opens each component using your own workspace permissions. App access does not automatically grant permission to inspect every resource.")
    if settings.use_ai_gateway:
        st.caption(f"The agent calls the Unity Gateway model service {settings.agent_endpoint}. Its link opens the containing Catalog Explorer schema; select the named service there.")
    st.subheader("What this reference implementation assumes")
    st.markdown("The collection is shared and new files are added on demand. Validation used 29 sample PDFs; larger collections need separate capacity testing. Replacing/deleting documents, persistent chat history, per-document permissions, production alerts, and other hardening steps are explained in the repository.")
    st.caption("Questions, chat context and retrieved passages are recorded in MLflow for evaluation and troubleshooting. Review retention and sensitive-data handling before using private customer documents.")
