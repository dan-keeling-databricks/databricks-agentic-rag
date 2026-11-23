# Run and look after your example

The quickstart creates the resources. Day-to-day use has two separate actions:
add documents when the collection changes, and evaluate answers when you change
the solution.

## Add documents

Upload new PDF files to the landing volume linked from the app, then run:

```bash
databricks bundle run ingest_documents -t demo --profile YOUR_PROFILE
```

This runs document preparation and then waits for a completed search-index
refresh. Auto Loader remembers previously seen files. Re-running does not mean
re-reading every unchanged PDF. Use new filenames: replacement and deletion
handling are outside this example's scope.

In Catalog Explorer, check `document_processing_status`. A `ready` row means
search preparation and metadata extraction completed. Other statuses identify
empty or oversized files, parsing/preparation problems, missing chunks, or
metadata errors. The intermediate tables retain the AI results and error details.
See [the pipeline guide](PIPELINE.md) for their meaning.

For a command-line check of stage counts, unique chunk identifiers, and pages:

```bash
python scripts/validate_data.py --profile YOUR_PROFILE \
  --catalog YOUR_CATALOG --warehouse-id YOUR_WAREHOUSE_ID
```

## Evaluate changes

Run the evaluation job and inspect its MLflow run:

```bash
databricks bundle run evaluate_agent -t demo --profile YOUR_PROFILE
```

The run contains the benchmark, generated answers, judge explanations, detailed
traces, and a report under **Artifacts → evaluation_report**. Compare like with
like: use the same question set, source documents, and judge model when comparing
agent or pipeline changes. See [evaluation](EVALUATION.md).

## Permissions

Deployment uses your explicitly selected profile. The app has its own Databricks
service identity. It can call the governed agent model, read the shared index
and landing volume, and write/read its MLflow experiment and separate trace
schema. A SQL warehouse is used for trace queries. App users do not automatically
gain access to the underlying resources just because they can use chat.

Grant people permission to use the app through its Databricks permissions page.
The example does not grant app access to everyone in the workspace. Everyone
you authorize sees the same searchable document collection.

Questions, chat context, retrieved passages, model calls, and answers may appear
in traces. Decide who may inspect those traces and how long to keep them before
loading customer-sensitive material.

## Troubleshoot a failed run

Open the job run, then the failing task. For document preparation, follow the
pipeline link and read the error on that specific update. For search, check the
index's detailed state; a queryable index can still have a failed latest update.
For chat, inspect app logs and the corresponding MLflow trace.

The command below follows the app logs; stop it with Ctrl+C:

```bash
databricks apps logs YOUR_APP_NAME --follow --profile YOUR_PROFILE
```

`databricks apps validate` currently validates AppKit projects. This Streamlit
project is checked with Python/Streamlit tests, strict bundle validation, live
ingestion/search, a persisted agent trace, and actual evaluation instead.

## Costs and cleanup

Parsing, search preparation, extraction, embeddings, answers, and judges consume
managed AI services. Apps, AI Search, pipeline runs, jobs, storage, and the trace
warehouse can also incur costs. On-demand ingestion limits repeated processing;
full refresh can repeat the expensive AI steps. There is no capacity or cost
guarantee for the 1,000-PDF sizing assumption.

The search endpoint belongs to the bundle. Its index is created by the ingestion
job after the source table exists. Before destroying the bundle, remove that
dedicated index if needed; otherwise it can keep the endpoint or schema in use.
Export any PDFs, evaluation artifacts, and traces you want to keep. Never delete
an entire shared catalog to clean up this solution. Review the target/profile
before using the quickstart's destructive cleanup command.
