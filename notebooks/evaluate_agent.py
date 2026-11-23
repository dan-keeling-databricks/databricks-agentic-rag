# Databricks notebook source
# MAGIC %md
# MAGIC # Evaluate the PDF assistant with MLflow
# MAGIC This is the native MLflow `evaluate()` workflow for a custom prediction
# MAGIC function. It loads the experiment's managed dataset and registered scorers,
# MAGIC then calls the same LangGraph agent as the app. MLflow handles execution,
# MAGIC assessments, traces, aggregate metrics, and the results UI.
# MAGIC
# MAGIC Open the experiment's **Evaluation runs** to compare runs and inspect each
# MAGIC answer and judge explanation. There is no separate evaluation report store.

# COMMAND ----------

import json
import os
import sys
from pathlib import Path

root = Path(dbutils.widgets.get("source_root"))
sys.path.insert(0, str(root))
experiment_id = dbutils.widgets.get("experiment_id")
os.environ.update({
    "AGENT_ENDPOINT": dbutils.widgets.get("agent_endpoint"),
    "JUDGE_ENDPOINT": dbutils.widgets.get("judge_endpoint"),
    "VECTOR_SEARCH_INDEX": dbutils.widgets.get("index_name"),
    "MLFLOW_EXPERIMENT_ID": experiment_id,
    "MLFLOW_TRACING_SQL_WAREHOUSE_ID": dbutils.widgets.get("warehouse_id"),
    "USE_AI_GATEWAY": "true",
})
os.environ.setdefault("MLFLOW_GENAI_EVAL_MAX_WORKERS", "2")

import mlflow
from evaluation.checks import implementation_fingerprint
from evaluation.dataset import pinned_dataset
from evaluation.scorers import load_scorers
from src.rag.agent import RagAgent, configure_tracing
from src.rag.config import Settings

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(experiment_id=experiment_id)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Read saved versions
# MAGIC Blank version parameters resolve the latest saved versions once at the
# MAGIC start. The exact dataset and scorer versions are recorded with the run.
# MAGIC Supply those parameters when reproducing a previous result.
# MAGIC Setup is deliberately separate, so rerunning evaluation preserves edits
# MAGIC made to the managed dataset and scorer registry.

# COMMAND ----------

dataset = pinned_dataset(
    dbutils.widgets.get("dataset_name"), dbutils.widgets.get("dataset_version")
)
requested_versions = json.loads(dbutils.widgets.get("scorer_versions") or "{}")
scorers = load_scorers(experiment_id, requested_versions or None)
versions = {item.name: item.scorer_version for item in scorers}
settings = Settings.from_env()
configure_tracing(settings)
agent = RagAgent(settings)


def predict(query, history=None):
    # MLflow passes only the managed record's inputs. Reference answers and
    # evidence are expectations and are visible to scorers only.
    return agent.answer(query=query, history=history)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Run evaluation
# MAGIC The managed dataset is passed directly to MLflow, preserving its native
# MAGIC identity and version lineage. Scorer failures appear in the run; they are
# MAGIC never replaced by passing results. Review failures as well as averages.

# COMMAND ----------

with mlflow.start_run(run_name="managed-benchmark"):
    mlflow.log_params({
        "dataset_name": dataset.name,
        "dataset_version": dataset.version,
        "dataset_digest": dataset.digest,
        "question_count": len(dataset.to_df()),
        "scorer_versions": json.dumps(versions, sort_keys=True),
        "agent_endpoint": settings.agent_endpoint,
        "judge_endpoint": settings.judge_endpoint,
        "vector_search_index": settings.vector_search_index,
        "max_searches": settings.max_searches,
        "retrieval_k": settings.retrieval_k,
        "max_context_characters": settings.max_context_characters,
        "max_history_messages": settings.max_history_messages,
        "implementation_sha256": implementation_fingerprint(root)["implementation_sha256"],
    })
    mlflow.set_tag("evaluation_workflow", "managed_dataset_registered_scorers")
    results = mlflow.genai.evaluate(data=dataset, predict_fn=predict, scorers=scorers)
    print(f"MLflow evaluation run: {results.run_id}")
    print(results)
    # A poor answer remains a valid measurement. Missing execution or scorer
    # results mean the benchmark is incomplete and should fail the notebook job.
    rows = results.result_df
    if rows is None or len(rows) != len(dataset.to_df()):
        raise RuntimeError("Evaluation did not return every managed dataset record; inspect the MLflow run.")
    errors = rows.filter(regex=r"(^error_message$|/error_message$)")
    if errors.notna().any().any():
        raise RuntimeError("Evaluation has prediction or scorer errors; inspect the MLflow run.")
    if "answerable/value" not in rows or not rows["answerable/value"].isin([True, False]).all():
        raise RuntimeError("Missing answerability expectations in MLflow results; inspect the MLflow run.")
    for item in scorers:
        # MLflow's native result table flattens expectation assessments too.
        applicable = rows["answerable/value"].map(
            lambda answerable: answerable or item.name not in {"retrieval_quality", "evidence_recall"}
        )
        if f"{item.name}/value" not in rows or rows.loc[applicable, f"{item.name}/value"].isna().any():
            raise RuntimeError(f"Missing applicable {item.name} assessments; inspect the MLflow run.")
