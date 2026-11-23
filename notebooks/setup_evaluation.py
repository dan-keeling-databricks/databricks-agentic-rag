# Databricks notebook source
# MAGIC %md
# MAGIC # Set up evaluation in MLflow
# MAGIC Run this once after deploying the bundle. It creates the experiment's
# MAGIC managed question dataset and registers its scorer definitions. An existing
# MAGIC dataset is left unchanged, including any customer edits and added questions.
# MAGIC Rerun this notebook deliberately after changing scorer definitions to publish
# MAGIC new versions. The benchmark notebook never reseeds or registers anything.
# MAGIC
# MAGIC Dependencies come from the bundle's serverless notebook environment.

# COMMAND ----------

import os
import sys
from pathlib import Path

root = Path(dbutils.widgets.get("source_root"))
sys.path.insert(0, str(root))
experiment_id = dbutils.widgets.get("experiment_id")
dataset_name = dbutils.widgets.get("dataset_name")
judge_endpoint = dbutils.widgets.get("judge_endpoint")
os.environ["MLFLOW_TRACING_SQL_WAREHOUSE_ID"] = dbutils.widgets.get("warehouse_id")

import mlflow

mlflow.set_tracking_uri("databricks")
mlflow.set_experiment(experiment_id=experiment_id)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Create the managed dataset
# MAGIC The JSONL file is a portable starting point. After this step, use
# MAGIC **Datasets** inside the experiment to inspect and edit the saved questions
# MAGIC and reference answers. Evaluation reads that managed copy.

# COMMAND ----------

from evaluation.checks import load_benchmark
from evaluation.dataset import initialize_dataset

dataset = initialize_dataset(
    dataset_name, experiment_id, load_benchmark(root / "evaluation/benchmark.jsonl")
)
print(f"Managed dataset: {dataset.name} ({dataset.dataset_id})")
print(f"Saved questions: {len(dataset.to_df())}. Inspect references in the experiment's Datasets area.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Register scorer versions
# MAGIC AI judges and deterministic checks are saved under **Scorers** in this
# MAGIC experiment. No continuous scoring of live user traffic is enabled here.

# COMMAND ----------

from evaluation.scorers import register_scorers

versions = register_scorers(experiment_id, judge_endpoint)
print("Registered scorer versions:", versions)
print(f"Open experiment {experiment_id}: Datasets, Scorers, and Evaluation runs.")
