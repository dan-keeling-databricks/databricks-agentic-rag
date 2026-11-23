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

Complete the explicit `setup_evaluation` job once to seed the managed dataset
and register scorers. Maintain questions and reviewed answers in the MLflow
experiment's **Datasets** area, and inspect scoring definitions in **Scorers**.
An ordinary evaluation does not reseed the questions or register new versions.

Run the evaluation notebook job and inspect its native MLflow run:

```bash
databricks bundle run evaluate_agent -t demo --profile YOUR_PROFILE
```

The run contains generated answers, assessments, judge explanations and detailed
traces. The managed dataset, registered scorer versions and evaluation runs are
the working record; no standalone report file is required. Compare like with
like: use the same dataset revision, scorer versions, source documents and judge
model when comparing agent or pipeline changes. See [evaluation](EVALUATION.md).

Use **Run evaluation → Use code** to work with the supplied notebook and its
custom scoring functions. **Select traces** can rescore recorded answers that
have the required reference expectations. Registering a scorer does not enable
continuous production monitoring in this reference.

## Inspect agent activity

The **Agent activity** tab shows the graph built by the LangGraph agent and
recent saved answer traces from this deployment's MLflow experiment. Select a
run to review its timestamp and steps: planned/refined search queries, retrieved
passages, model inputs and outputs, evidence assessments, and the final response.
These are recorded operations and explicit structured decisions. The display
does not provide hidden internal model reasoning.

Refresh the recent-runs list to pick up newer traces. Allow time for a completed
answer's trace to reach Unity Catalog. Open the MLflow trace link for the full
record. If the list is empty or a trace cannot load, check the experiment,
trace-read permissions, and configured SQL warehouse; an empty list is not proof
that no one has asked a question.

## Permissions

Deployment uses your explicitly selected profile. The app has its own Databricks
service identity. It can call the governed agent model, read the shared index
and landing volume, and write/read its MLflow experiment and separate trace
schema. A SQL warehouse is used for trace queries. App users do not automatically
gain access to the underlying resources just because they can use chat.

Grant people permission to use the app through its Databricks permissions page.
The example does not grant app access to everyone in the workspace. Everyone
you authorize sees the same searchable document collection.

Every authorized app user can also browse the shared historical answer traces
in **Agent activity** through the app's service identity. This includes saved
questions, document passages, and model inputs and outputs from other runs.
The tab does not filter history to the current user's chat session.

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
guarantee for larger document collections.

The search endpoint belongs to the bundle. Its index is created by the ingestion
job after the source table exists. Before destroying the bundle, remove that
dedicated index if needed; otherwise it can keep the endpoint or schema in use.
Export any PDFs, managed evaluation questions, runs and traces you want to keep. Never delete
an entire shared catalog to clean up this solution. Review the target/profile
before using the quickstart's destructive cleanup command.
