"""Checks for benchmark integrity and misleading evaluation results."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evaluation.checks import (
    IMPLEMENTATION_FILES, implementation_fingerprint, load_benchmark,
)
from evaluation.dataset import initialize_dataset, pinned_dataset, seed_records
from evaluation.scorers import evidence_recall, valid_citations
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
    for row, data in zip(rows, seed_records(rows)):
        assert set(data["inputs"]) == {"query", "history"}
        question_and_history = json.dumps(row["inputs"], ensure_ascii=False).casefold()
        assert not any(hint in question_and_history for hint in filenames | source_titles)
        assert not any(hint in question_and_history for hint in (".pdf", "the ebook", "the guide", "same guide"))
        assert "expected_response" not in data["inputs"]
        assert "expected_facts" not in data["inputs"]
        assert "evidence" not in data["inputs"]


def test_reference_cannot_change_document_or_extend_retrieved_pages():
    retrieved = {"chunk_id": "a", "filename": "first.pdf", "page_start": 2, "page_end": 3}
    outputs = {"retrieved_context": [retrieved], "sources": [{**retrieved, "filename": "second.pdf"}]}
    assert valid_citations(outputs=outputs, expectations={"answerable": True}).value is False
    outputs["sources"] = [{**retrieved, "page_end": 4}]
    assert valid_citations(outputs=outputs, expectations={"answerable": True}).value is False
    outputs["sources"] = [retrieved]
    assert valid_citations(outputs=outputs, expectations={"answerable": True}).value is True


def test_abstention_has_no_fake_retrieval_recall_score():
    assert evidence_recall(outputs={"retrieved_context": []}, expectations={"answerable": False}) == []
    assert valid_citations(outputs={"sources": []}, expectations={"answerable": False}).value is True
    assert valid_citations(outputs={"sources": []}, expectations={"answerable": True}).value is False


def test_recall_uses_document_page_pairs_not_duplicate_evidence_quotes():
    expectations = {"answerable": True, "evidence_json": json.dumps([
        {"filename": "a.pdf", "page": 2}, {"filename": "a.pdf", "page": 2},
        {"filename": "b.pdf", "page": 2},
    ])}
    outputs = {"retrieved_context": [{"filename": "a.pdf", "page_start": 1, "page_end": 3}]}
    assert evidence_recall(outputs=outputs, expectations=expectations).value == 0.5


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


def test_managed_seed_expectations_preserve_full_facts_and_evidence_as_editable_json():
    row = next(row for row in load_benchmark(BENCHMARK) if row["category"] == "multi_document")
    original = json.loads(json.dumps(row))
    data = seed_records([row])[0]
    assert set(data["expectations"]) == {
        "expected_response", "answerable", "review_status", "corpus_revision",
        "expected_facts_json", "evidence_json", "question_id", "category",
    }
    assert all(isinstance(value, (str, bool)) for value in data["expectations"].values())
    assert data["expectations"]["question_id"] == row["id"]
    assert data["expectations"]["category"] == row["category"]
    assert json.loads(data["expectations"]["expected_facts_json"]) == row["expectations"]["expected_facts"]
    assert json.loads(data["expectations"]["evidence_json"]) == row["expectations"]["evidence"]
    assert row == original  # Seeding must not mutate the checked-in reference records.


def dataset_api(monkeypatch, existing):
    import databricks.sdk
    from databricks.sdk.errors import NotFound
    import mlflow.genai.datasets

    workspace = Mock()
    if not existing:
        workspace.tables.get.side_effect = NotFound("Dataset table does not exist")
    monkeypatch.setattr(databricks.sdk, "WorkspaceClient", Mock(return_value=workspace))
    dataset = Mock(dataset_id="dataset-id", experiment_ids=["experiment"])
    create = Mock(return_value=dataset)
    get = Mock(return_value=dataset)
    attach = dataset.add_to_experiments
    monkeypatch.setattr(mlflow.genai.datasets, "create_dataset", create)
    monkeypatch.setattr(mlflow.genai.datasets, "get_dataset", get)
    return workspace, dataset, create, get, attach


def test_repeated_setup_preserves_reviewed_managed_dataset_records(monkeypatch):
    workspace, dataset, create, get, attach = dataset_api(monkeypatch, existing=True)
    records = load_benchmark(BENCHMARK)
    assert initialize_dataset("catalog.rag.benchmark", "experiment", records) is dataset
    workspace.tables.get.assert_called_once_with("catalog.rag.benchmark")
    create.assert_not_called()
    dataset.merge_records.assert_not_called()
    attach.assert_not_called()
    assert all(call.kwargs == {"name": "catalog.rag.benchmark"} for call in get.call_args_list)


def test_existing_managed_dataset_links_an_additional_experiment_without_reseeding(monkeypatch):
    _, dataset, create, _, attach = dataset_api(monkeypatch, existing=True)
    dataset.experiment_ids = ["other-experiment"]
    initialize_dataset("catalog.rag.benchmark", "experiment", load_benchmark(BENCHMARK))
    attach.assert_called_once_with(["experiment"])
    create.assert_not_called()
    dataset.merge_records.assert_not_called()


def test_first_setup_seeds_dataset_with_no_reference_fields_in_agent_inputs(monkeypatch):
    _, dataset, create, _, attach = dataset_api(monkeypatch, existing=False)
    records = load_benchmark(BENCHMARK)
    assert initialize_dataset("catalog.rag.benchmark", "experiment", records) is dataset
    create.assert_called_once_with(name="catalog.rag.benchmark", experiment_id="experiment")
    dataset.merge_records.assert_called_once_with(seed_records(records))
    attach.assert_not_called()


def test_dataset_permission_error_is_not_mistaken_for_absent_dataset(monkeypatch):
    workspace, dataset, create, _, attach = dataset_api(monkeypatch, existing=True)
    from databricks.sdk.errors import PermissionDenied
    workspace.tables.get.side_effect = PermissionDenied("No read permission")
    with pytest.raises(PermissionDenied):
        initialize_dataset("catalog.rag.benchmark", "experiment", load_benchmark(BENCHMARK))
    create.assert_not_called()
    dataset.merge_records.assert_not_called()
    attach.assert_not_called()


def test_latest_managed_dataset_is_pinned_to_highest_version_once(monkeypatch):
    _, dataset, _, get, _ = dataset_api(monkeypatch, existing=True)
    dataset.list_versions.return_value = [SimpleNamespace(version=3), SimpleNamespace(version=1)]
    pinned = Mock()
    get.side_effect = [dataset, pinned]
    assert pinned_dataset("catalog.rag.benchmark") is pinned
    assert get.call_args_list[-1].kwargs == {"name": "catalog.rag.benchmark", "version": 3}


def test_explicit_managed_dataset_version_does_not_follow_latest(monkeypatch):
    _, dataset, _, get, _ = dataset_api(monkeypatch, existing=True)
    pinned = Mock()
    get.side_effect = [dataset, pinned]
    assert pinned_dataset("catalog.rag.benchmark", "1") is pinned
    dataset.list_versions.assert_not_called()
    assert get.call_args_list[-1].kwargs == {"name": "catalog.rag.benchmark", "version": 1}


@pytest.fixture
def native_registry_context():
    """Enable MLflow's Databricks custom-scorer deserializer without calling APIs."""
    import mlflow

    previous_uri = mlflow.get_tracking_uri()
    mlflow.set_tracking_uri("databricks://unit-test")
    try:
        yield
    finally:
        mlflow.set_tracking_uri(previous_uri)


def test_native_judges_roundtrip_the_registered_definition_and_model(native_registry_context):
    from evaluation.scorers import Scorer, build_scorers

    definitions = build_scorers("catalog.rag.judge")
    for name in ("correctness", "groundedness", "retrieval_quality_judge"):
        payload = json.loads(json.dumps(definitions[name].model_dump()))
        restored = Scorer.model_validate(payload)
        judge = restored.model_dump()["instructions_judge_pydantic_data"]
        assert restored.name == name
        assert judge["model"] == "databricks:/catalog.rag.judge"
        assert judge["feedback_value_type"]["type"] == "boolean"
        assert "outputs" in judge["instructions"]
        assert "call_source" not in judge  # Native judges serialize their instructions, not a custom LLM call.


def test_registered_code_checks_execute_after_source_only_roundtrip(native_registry_context):
    from evaluation.scorers import Scorer, build_scorers

    definitions = build_scorers("catalog.rag.judge")
    restored = {
        name: Scorer.model_validate(json.loads(json.dumps(definitions[name].model_dump())))
        for name in ("valid_citations", "evidence_recall", "latency_seconds")
    }
    source = {"chunk_id": "source", "filename": "a.pdf", "page_start": 2, "page_end": 3}
    output = {"sources": [source], "retrieved_context": [source], "latency_seconds": 1.5}
    reference = {"answerable": True, "evidence_json": json.dumps([
        {"filename": "a.pdf", "page": 2}, {"filename": "a.pdf", "page": 2},
        {"filename": "b.pdf", "page": 2},
    ])}
    assert restored["valid_citations"](outputs=output, expectations=reference).value is True
    invalid = {**output, "sources": [{**source, "page_end": 4}]}
    assert restored["valid_citations"](outputs=invalid, expectations=reference).value is False
    assert restored["evidence_recall"](outputs=output, expectations=reference).value == 0.5
    assert restored["latency_seconds"](outputs=output).value == 1.5
    assert restored["latency_seconds"].aggregations == ["mean", "median", "p90", "max"]
    assert restored["evidence_recall"](outputs={}, expectations={"answerable": False}) == []
    with pytest.raises(ValueError, match="reference pages"):
        restored["evidence_recall"](outputs={}, expectations={"answerable": True, "evidence_json": "[]"})


@pytest.mark.parametrize("elapsed", [-1, float("nan"), float("inf")])
def test_registered_latency_check_rejects_invalid_measurements(native_registry_context, elapsed):
    from evaluation.scorers import Scorer, latency_seconds

    restored = Scorer.model_validate(json.loads(json.dumps(latency_seconds.model_dump())))
    with pytest.raises(ValueError, match="finite, nonnegative"):
        restored(outputs={"latency_seconds": elapsed})


def test_retrieval_wrapper_roundtrip_pins_native_judge_and_skips_inapplicable_rows(
    monkeypatch, native_registry_context,
):
    import mlflow.genai.scorers
    from mlflow.entities import Feedback
    from evaluation.scorers import Scorer, _pinned_retrieval_wrapper

    wrapper = _pinned_retrieval_wrapper("123", 7)
    restored = Scorer.model_validate(json.loads(json.dumps(wrapper.model_dump())))
    judge = Mock(scorer_version=7, return_value=Feedback(value=False, rationale="Missing a required fact."))
    lookup = Mock(return_value=judge)
    monkeypatch.setattr(mlflow.genai.scorers, "get_scorer", lookup)
    assert restored(inputs={}, outputs={}, expectations={"answerable": False}) == []
    lookup.assert_not_called()
    result = restored(inputs={"query": "question"}, outputs={}, expectations={"answerable": True})
    lookup.assert_called_once_with(name="retrieval_quality_judge", experiment_id="123", version=7)
    assert result.name == "retrieval_quality" and result.value is False
    assert result.rationale == "Missing a required fact."
    assert result.metadata["native_judge_version"] == "7"


def test_registration_pins_wrapper_to_the_version_returned_for_its_native_judge(
    monkeypatch, native_registry_context,
):
    from evaluation import scorers as native

    registered = []

    def register(definition, experiment_id):
        assert experiment_id == "123"
        registered.append(json.loads(json.dumps(definition.model_dump())))
        return SimpleNamespace(scorer_version=len(registered))

    monkeypatch.setattr(native.Scorer, "register", register)
    versions = native.register_scorers("123", "catalog.rag.judge")
    assert len(registered) == len(versions) == 7
    wrapper = next(item for item in registered if item["name"] == "retrieval_quality")
    judge_version = versions["retrieval_quality_judge"]
    assert f"version={judge_version}" in wrapper["call_source"]
    assert "__PINNED_EXPERIMENT_ID__" not in wrapper["call_source"]
    assert "-123456789" not in wrapper["call_source"]


def test_loading_registered_scorers_requires_complete_versions_and_resolves_each_once(monkeypatch):
    from evaluation import scorers as native

    lookup = Mock(side_effect=lambda **kwargs: kwargs)
    monkeypatch.setattr(native, "get_scorer", lookup)
    with pytest.raises(ValueError, match="every evaluation scorer"):
        native.load_scorers("123", {"correctness": 1})
    lookup.assert_not_called()
    versions = {name: i + 1 for i, name in enumerate(native.EVALUATION_SCORER_NAMES)}
    loaded = native.load_scorers("123", versions)
    assert {item["name"]: item["version"] for item in loaded} == versions
    assert lookup.call_count == 6
