"""Portable seed records for the experiment's MLflow-managed evaluation dataset.

The JSONL file is used only during explicit setup. Normal evaluations read the
managed dataset, so edits made in MLflow are preserved.
"""

import json


def seed_records(records: list[dict]) -> list[dict]:
    """Keep every reference field in MLflow, separate from the agent's inputs.

    JSON strings preserve lists through this workspace's UC trace expectation
    readback. They are ordinary editable dataset expectations, not a second
    reference store. Scorers decode them where needed.
    """
    result = []
    for row in records:
        expected = dict(row["expectations"])
        for field in ("expected_facts", "evidence"):
            expected[f"{field}_json"] = json.dumps(expected.pop(field), ensure_ascii=False)
        result.append({
            "inputs": dict(row["inputs"]),
            "expectations": {**expected, "question_id": row["id"], "category": row["category"]},
        })
    return result


def initialize_dataset(name: str, experiment_id: str, records: list[dict]):
    """Create and seed once; leave an existing dataset untouched.

    Dataset changes belong in the experiment UI or an explicit merge_records()
    call. Repeating deployment must not overwrite reviewed reference answers.
    """
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.errors import NotFound
    from mlflow.genai.datasets import create_dataset, get_dataset

    try:
        WorkspaceClient().tables.get(name)
    except NotFound:
        dataset = create_dataset(name=name, experiment_id=experiment_id)
        dataset.merge_records(seed_records(records))
    else:
        dataset = get_dataset(name=name)
        # The module-level association API is not implemented for Databricks.
        # Its managed dataset handle exposes the UC-backed association method.
        if str(experiment_id) not in (dataset.experiment_ids or []):
            dataset.add_to_experiments([str(experiment_id)])
    return get_dataset(name=name)


def pinned_dataset(name: str, version: str = ""):
    """Resolve latest once, then read that immutable Delta version for the run."""
    from mlflow.genai.datasets import get_dataset

    latest = get_dataset(name=name)
    resolved = int(version) if version else max(item.version for item in latest.list_versions())
    return get_dataset(name=name, version=resolved)
