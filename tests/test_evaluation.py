"""Checks for benchmark integrity and misleading evaluation results."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evaluation.checks import citation_validity, evidence_page_recall, load_benchmark
from evaluation.runner import AIJudge, write_report
from scripts.smoke_agent import check_trace, trace_browser_url


BENCHMARK = Path(__file__).resolve().parents[1] / "evaluation" / "benchmark.jsonl"


def test_benchmark_covers_agreed_behaviors_and_has_page_evidence():
    rows = load_benchmark(BENCHMARK)
    assert len(rows) == 20
    assert {row["category"] for row in rows} == {"factual", "multi_document", "follow_up", "unanswerable"}
    for row in rows:
        assert row["expectations"]["review_status"] == "author_derived_pending_customer_review"
        if row["category"] == "multi_document":
            assert len({item["filename"] for item in row["expectations"]["evidence"]}) >= 2
        if row["category"] == "follow_up":
            assert row["inputs"]["history"]
        for item in row["expectations"]["evidence"]:
            assert item["page"] >= 1 and item["quote"].strip()


def test_reference_cannot_change_document_or_extend_retrieved_pages():
    retrieved = {"chunk_id": "a", "filename": "first.pdf", "page_start": 2, "page_end": 3}
    outputs = {"retrieved_context": [retrieved], "sources": [{**retrieved, "filename": "second.pdf"}]}
    assert citation_validity(outputs, {"answerable": True})[0] is False
    outputs["sources"] = [{**retrieved, "page_end": 4}]
    assert citation_validity(outputs, {"answerable": True})[0] is False
    outputs["sources"] = [retrieved]
    assert citation_validity(outputs, {"answerable": True})[0] is True


def test_abstention_has_no_fake_retrieval_recall_score():
    assert evidence_page_recall({"retrieved_context": []}, {"evidence": []})[0] is None
    assert citation_validity({"sources": []}, {"answerable": False})[0] is True
    assert citation_validity({"sources": []}, {"answerable": True})[0] is False


def test_recall_uses_document_page_pairs_not_duplicate_evidence_quotes():
    expectations = {"evidence": [{"filename": "a.pdf", "page": 2}, {"filename": "a.pdf", "page": 2},
                                {"filename": "b.pdf", "page": 2}]}
    outputs = {"retrieved_context": [{"filename": "a.pdf", "page_start": 1, "page_end": 3}]}
    assert evidence_page_recall(outputs, expectations)[0] == 0.5


class StubCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))])


def test_judge_does_not_treat_string_false_as_a_passing_boolean():
    client = SimpleNamespace(chat=SimpleNamespace(completions=StubCompletions('{"pass":"false","rationale":"bad"}')))
    with pytest.raises(ValueError, match="boolean"):
        AIJudge(client, "judge").assess("criterion", {})


def test_judge_accepts_json_fence_and_preserves_failure_explanation():
    client = SimpleNamespace(chat=SimpleNamespace(completions=StubCompletions('```json\n{"pass":false,"rationale":"Unsupported claim"}\n```')))
    assert AIJudge(client, "judge").assess("criterion", {}) == (False, "Unsupported claim")


def test_report_discloses_incomplete_scoring_and_specific_failures(tmp_path):
    path = tmp_path / "BASELINE.md"
    write_report(path, {"created_at": "now", "run_url": "https://example/run", "completed_questions": 1,
                        "question_count": 2, "missing_assessments": 1, "metrics": {}},
                 [{"id": "q01", "scores": {"correctness": {"value": False, "rationale": "Wrong amount"}}}])
    content = path.read_text()
    assert "1 / 2" in content and "**1**" in content
    assert "q01 / correctness" in content and "Wrong amount" in content


def test_trace_verification_requires_model_retrieval_graph_and_actual_request():
    def span(kind):
        return SimpleNamespace(span_type=kind, inputs={"query": "question"}, outputs={"text": "evidence"})
    trace = SimpleNamespace(info=SimpleNamespace(request_time=150),
                            data=SimpleNamespace(request={"query": "question"},
                                                 spans=[span(k) for k in ["AGENT", "CHAIN", "CHAT_MODEL", "RETRIEVER"]]))
    assert check_trace(trace, "question", 100, 200)["model_spans"] == 1
    with pytest.raises(RuntimeError, match="question"):
        check_trace(trace, "unrelated request", 100, 200)
    trace.data.spans = [span("AGENT"), span("CHAIN"), span("RETRIEVER")]
    with pytest.raises(RuntimeError, match="model spans"):
        check_trace(trace, "question", 100, 200)


def test_browser_link_strips_only_qualified_uc_prefix():
    assert trace_browser_url("https://workspace/", "123", "trace:/catalog.schema/abc") == "https://workspace/ml/experiments/123/traces/abc"
    assert trace_browser_url("https://workspace", "123", "tr-abc").endswith("/traces/tr-abc")
