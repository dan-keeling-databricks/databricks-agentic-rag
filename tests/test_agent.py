"""Exercise termination, source integrity and session isolation without cloud calls."""

import json
from types import SimpleNamespace

import mlflow
import pytest

from src.rag.agent import INSUFFICIENT_EVIDENCE, RagAgent, render_claims
from src.rag.config import Settings
from src.rag.links import architecture_links, trace_url
from src.rag.retrieval import decode_search_results


@pytest.fixture(autouse=True)
def no_trace_export():
    previous_uri = mlflow.get_tracking_uri()
    mlflow.set_tracking_uri("sqlite:///:memory:")
    mlflow.tracing.disable()
    yield
    mlflow.tracing.enable()
    mlflow.set_tracking_uri(previous_uri)


def document(chunk_id="one", **changes):
    return {"chunk_id": chunk_id, "filename": "guide.pdf", "content": "Auto Loader ingests new files.",
            "source_path": "/Volumes/test/rag/pdfs/guide.pdf", "page_start": 2, "page_end": 3,
            **changes}


class FakeModel:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(self.replies))))])


class FakeRetriever:
    def __init__(self, rounds):
        self.rounds = iter(rounds)
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return next(self.rounds)


def agent(model, retriever, **settings):
    return RagAgent(Settings("model", "test.rag.index", **settings),
                    workspace_client=object(), model_client=model, retriever=retriever)


def test_search_limit_terminates_even_when_evidence_never_suffices():
    model = FakeModel([{"search_query": "initial"}] + [
        {"sufficient": False, "next_query": "try again"} for _ in range(3)
    ])
    retriever = FakeRetriever([[document()]] * 3)
    result = agent(model, retriever).answer("What is missing?")
    assert result["search_count"] == 3
    assert len(retriever.queries) == 3
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["sources"] == []


def test_empty_search_results_never_trigger_an_unsupported_answer():
    model = FakeModel([{"search_query": "unknown"}])
    result = agent(model, FakeRetriever([[], []]), max_searches=2).answer("Unknown fact?")
    assert result["answer"] == INSUFFICIENT_EVIDENCE
    assert result["search_count"] == 1
    assert len(model.requests) == 1


def test_answer_uses_deterministic_document_and_page_citations():
    model = FakeModel([
        {"search_query": "Auto Loader"}, {"sufficient": True},
        {"claims": [{"text": "Auto Loader ingests new files.", "source_ids": ["S1"]}]},
    ])
    result = agent(model, FakeRetriever([[document()]])).answer("What does Auto Loader do?")
    assert result["answer"] == "Auto Loader ingests new files. [guide.pdf, p. 2–3]"
    assert result["sources"][0]["chunk_id"] == "one"


def test_invented_source_id_discards_the_answer():
    answer, sources = render_claims(
        {"claims": [{"text": "An invented claim.", "source_ids": ["S99"]}]},
        [{**document(), "source_id": "S1"}],
    )
    assert answer == INSUFFICIENT_EVIDENCE
    assert sources == []


def test_multi_document_claim_retains_both_sources():
    docs = [{**document(), "source_id": "S1"},
            {**document("two", filename="second.pdf", page_start=1, page_end=1), "source_id": "S2"}]
    answer, sources = render_claims({"claims": [{"text": "Combined evidence.", "source_ids": ["S1", "S2"]}]}, docs)
    assert "[second.pdf, p. 1]" in answer
    assert len(sources) == 2


def test_follow_up_context_is_passed_but_not_retained_between_calls():
    model = FakeModel([
        {"search_query": "Auto Loader history"}, {"sufficient": True},
        {"claims": [{"text": "It reads files.", "source_ids": ["S1"]}]},
        {"search_query": "new topic"},
    ])
    shared = agent(model, FakeRetriever([[document()], []]), max_searches=1)
    shared.answer("How does it work?", history=[{"role": "user", "content": "Tell me about Auto Loader"}])
    shared.answer("New session question")
    assert "Tell me about Auto Loader" in model.requests[0]["messages"][1]["content"]
    assert json.loads(model.requests[3]["messages"][1]["content"])["history"] == []


def test_index_manifest_order_is_respected_and_unknown_pages_are_excluded():
    result = decode_search_results({
        "manifest": {"columns": [{"name": n} for n in ["filename", "page_end", "chunk_id", "page_start", "chunk_to_retrieve"]]},
        "result": {"data_array": [["guide.pdf", 3, "one", 2, "text"], ["bad.pdf", None, "two", None, "text"]]},
    })
    assert len(result) == 1
    assert result[0]["page_start"] == 2
    assert result[0]["content"] == "text"


@pytest.mark.parametrize("host", ["https://workspace.example", "https://workspace.example/", "workspace.example", "workspace.example/"])
def test_links_use_deployment_configuration_and_uc_trace_id(host):
    settings = Settings("catalog.schema.agent_model", "catalog.schema.search", pipeline_id="pipeline-id", source_volume="catalog.schema.pdfs")
    links = architecture_links(host, settings)
    assert links["Document processing pipeline"] == "https://workspace.example/pipelines/pipeline-id"
    assert links["PDF landing volume"] == "https://workspace.example/explore/data/volumes/catalog/schema/pdfs"
    assert links["Agent model service: catalog.schema.agent_model (open schema)"] == "https://workspace.example/explore/data/catalog/schema"
    assert trace_url(host, "123", "trace:/catalog.schema/abc") == "https://workspace.example/ml/experiments/123/traces/abc"


def test_invalid_search_limits_are_rejected():
    with pytest.raises(ValueError, match="MAX_SEARCHES"):
        Settings("model", "catalog.schema.index", max_searches=0)
