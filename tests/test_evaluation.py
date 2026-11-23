"""Checks for benchmark integrity and misleading evaluation results."""

import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from evaluation.checks import (
    IMPLEMENTATION_FILES, citation_validity, evidence_page_recall,
    implementation_fingerprint, load_benchmark,
)
from evaluation.runner import AIJudge, evaluation_data, make_scorers, model_service_metadata, write_report
from scripts.smoke_agent import check_trace, trace_browser_url


BENCHMARK = Path(__file__).resolve().parents[1] / "evaluation" / "benchmark.jsonl"


def test_benchmark_covers_supported_behaviors_and_has_page_evidence():
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


def test_agent_inputs_have_no_document_routing_hints_or_reference_answers():
    rows = load_benchmark(BENCHMARK)
    filenames = {item["filename"].casefold() for row in rows for item in row["expectations"]["evidence"]}
    source_titles = {
        "a compact guide to large language models", "all roads lead to the lakehouse",
        "making your digital twin come to life",
    }
    for row, data in zip(rows, evaluation_data(rows)):
        assert set(data["inputs"]) == {"query", "history", "question_id"}
        question_and_history = json.dumps(row["inputs"], ensure_ascii=False).casefold()
        assert not any(hint in question_and_history for hint in filenames | source_titles)
        assert not any(hint in question_and_history for hint in (".pdf", "the ebook", "the guide", "same guide"))
        assert "expected_response" not in data["inputs"]
        assert "expected_facts" not in data["inputs"]
        assert "evidence" not in data["inputs"]


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
        output = [{"page_content": "evidence"}] if kind == "RETRIEVER" else {"text": "evidence"}
        return SimpleNamespace(span_type=kind, inputs={"query": "question"}, outputs=output)
    trace = SimpleNamespace(info=SimpleNamespace(request_time=150),
                            data=SimpleNamespace(request={"query": "question"},
                                                 spans=[span(k) for k in ["AGENT", "CHAIN", "CHAT_MODEL", "RETRIEVER"]]))
    assert check_trace(trace, "question", 100, 200)["model_spans"] == 1
    with pytest.raises(RuntimeError, match="question"):
        check_trace(trace, "unrelated request", 100, 200)
    trace.data.spans = [span("AGENT"), span("CHAIN"), span("RETRIEVER")]
    with pytest.raises(RuntimeError, match="model spans"):
        check_trace(trace, "question", 100, 200)


def test_trace_verification_rejects_json_encoded_empty_retrieval():
    spans = [SimpleNamespace(span_type=kind, inputs='{"query":"question"}', outputs='{"text":"reply"}')
             for kind in ["AGENT", "CHAIN", "CHAT_MODEL"]]
    retrieval = SimpleNamespace(span_type="RETRIEVER", inputs='{"query":"question"}', outputs=json.dumps(json.dumps([])))
    trace = SimpleNamespace(info=SimpleNamespace(request_time=150),
                            data=SimpleNamespace(request='{"query":"question"}', spans=spans + [retrieval]))
    with pytest.raises(RuntimeError, match="retrieved evidence"):
        check_trace(trace, "question", 100, 200)
    retrieval.outputs = json.dumps(json.dumps([{"page_content": "actual evidence"}]))
    assert check_trace(trace, "question", 100, 200)["retrieval_spans"] == 1


def test_browser_link_strips_only_qualified_uc_prefix():
    assert trace_browser_url("https://workspace/", "123", "trace:/catalog.schema/abc") == "https://workspace/ml/experiments/123/traces/abc"
    assert trace_browser_url("https://workspace", "123", "tr-abc").endswith("/traces/tr-abc")


def test_code_fingerprint_changes_when_evaluated_source_changes(tmp_path):
    for relative_path in IMPLEMENTATION_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original source\n")
    first = implementation_fingerprint(tmp_path)
    assert first == implementation_fingerprint(tmp_path)
    (tmp_path / IMPLEMENTATION_FILES[0]).write_text("changed source\n")
    assert first["implementation_sha256"] != implementation_fingerprint(tmp_path)["implementation_sha256"]


def test_model_service_snapshot_records_destinations_and_lookup_failures():
    calls = []

    def get_model_service(name):
        calls.append(name)
        if name.endswith("judge"):
            raise PermissionError("Private diagnostic not needed in metadata")
        routing = SimpleNamespace(as_dict=lambda: {"destinations": [{"pay_per_token_config": {"model": "system.ai.agent"}}]})
        return SimpleNamespace(name=name, etag="revision1", config=SimpleNamespace(routing=routing))

    settings = SimpleNamespace(use_ai_gateway=True, agent_endpoint="catalog.schema.agent", judge_endpoint="catalog.schema.judge")
    result = model_service_metadata(SimpleNamespace(ai_gateway=SimpleNamespace(get_model_service=get_model_service)), settings)
    assert calls == ["model-services/catalog.schema.agent", "model-services/catalog.schema.judge"]
    assert result["agent"]["status"] == "resolved"
    assert result["agent"]["routing"]["destinations"][0]["pay_per_token_config"]["model"] == "system.ai.agent"
    assert result["judge"] == {"endpoint": "catalog.schema.judge", "status": "unavailable", "error_type": "PermissionError"}


def test_scalar_mlflow_expectations_preserve_full_facts_and_evidence_for_scorers():
    row = next(row for row in load_benchmark(BENCHMARK) if row["category"] == "multi_document")
    data = evaluation_data([row])[0]
    assert set(data["expectations"]) == {"expected_response", "answerable", "review_status", "corpus_revision"}
    assert all(isinstance(value, (str, bool)) for value in data["expectations"].values())
    payloads = []

    class RecordingJudge:
        endpoint = "judge-model"

        def assess(self, criterion, payload):
            payloads.append(payload)
            return True, "Checked the full reference facts."

    evidence = row["expectations"]["evidence"][0]
    source = {"chunk_id": "one", "filename": evidence["filename"],
              "page_start": evidence["page"], "page_end": evidence["page"], "content": evidence["quote"]}
    outputs = {"question_id": row["id"], "answer": "answer", "sources": [source],
               "retrieved_context": [source], "latency_seconds": 1.0}
    scorers = {scorer.name: scorer for scorer in make_scorers(
        RecordingJudge(), {}, threading.Lock(), {row["id"]: row["expectations"]})}
    scorers["correctness"](inputs=data["inputs"], outputs=outputs, expectations=data["expectations"])
    assert payloads[-1]["required_facts"] == row["expectations"]["expected_facts"]
    scorers["retrieval_quality"](inputs=data["inputs"], outputs=outputs, expectations=data["expectations"])
    assert payloads[-1]["required_facts"] == row["expectations"]["expected_facts"]
    assert scorers["valid_citations"](outputs=outputs, expectations=data["expectations"]).value is True
    # Both reference pages remain in the denominator despite scalar annotations.
    assert scorers["evidence_recall"](outputs=outputs, expectations=data["expectations"]).value == 0.5
    with pytest.raises(KeyError):
        scorers["evidence_recall"](outputs={**outputs, "question_id": "unknown"}, expectations=data["expectations"])


def test_not_applicable_scores_emit_no_null_feedback_but_remain_in_report():
    row = next(row for row in load_benchmark(BENCHMARK) if row["category"] == "unanswerable")
    data = evaluation_data([row])[0]
    log = {}

    class NoJudgeExpected:
        endpoint = "judge"

        def assess(self, criterion, payload):
            raise AssertionError("An inapplicable retrieval check must not call a judge.")

    scorers = {scorer.name: scorer for scorer in make_scorers(
        NoJudgeExpected(), log, threading.Lock(), {row["id"]: row["expectations"]})}
    outputs = {"question_id": row["id"], "retrieved_context": []}
    for name in ["retrieval_quality", "evidence_recall"]:
        feedback = scorers[name](inputs=data["inputs"], outputs=outputs, expectations=data["expectations"]) if name == "retrieval_quality" else scorers[name](outputs=outputs, expectations=data["expectations"])
        assert feedback == []  # Not Feedback(value=None), which the backend rejects.
        assert log[row["id"]][name]["value"] is None
        assert "Not applicable" in log[row["id"]][name]["rationale"]
