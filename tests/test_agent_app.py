"""Check the two-tab interface and configuration errors without a workspace."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = Path(__file__).parents[1] / "app.py"


def test_app_renders_chat_architecture_and_resource_links(monkeypatch):
    monkeypatch.setenv("AGENT_ENDPOINT", "catalog.rag.model")
    monkeypatch.setenv("VECTOR_SEARCH_INDEX", "catalog.rag.search")
    monkeypatch.setenv("DATABRICKS_HOST", "https://workspace.example")
    monkeypatch.setenv("SOURCE_VOLUME", "catalog.rag.pdfs")
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Chat", "Architecture"]
    assert app.title[0].value == "Ask your PDFs"
    assert app.chat_input[0].placeholder == "Ask a question about your PDFs"


def test_missing_configuration_shows_useful_action(monkeypatch):
    monkeypatch.delenv("AGENT_ENDPOINT", raising=False)
    monkeypatch.delenv("VECTOR_SEARCH_INDEX", raising=False)
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    assert "deployment configuration" in app.error[0].value
    assert "quickstart" in app.info[0].value
