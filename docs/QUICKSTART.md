# Deploy the PDF assistant

This guide deploys the solution into your Databricks workspace. You will create
its resources, load sample PDFs, and open the app.

The word **bundle** below means the configuration files that describe the
Databricks resources. A **profile** is a named Databricks CLI login that identifies
the workspace you want to use.

## Before you start

You need:

- Access to this private GitHub repository and a local clone.
- Python 3.11 and [uv](https://docs.astral.sh/uv/getting-started/installation/),
  or another way to create a Python virtual environment.
- A current [Databricks CLI](https://docs.databricks.com/dev-tools/cli/install),
  version 1.26.0 or newer, supporting the bundle resources used here.
- A Unity Catalog-enabled Databricks workspace and an existing catalog in which
  you can create the solution's schema, tables, and volume.
- Permission to deploy Databricks Apps, jobs, pipelines, an MLflow experiment,
  and AI Search resources, and to grant the app's service principal (its own
  identity for accessing resources) the access it needs.
- A usable SQL warehouse. Serverless is preferred. It is used for trace queries
  and validation checks; its ID is not a password.
- Access to compatible answer, judge, and embedding models. Defaults use
  open-weight models where available. The setup must verify model/gateway
  permissions in your workspace.
- Support for the three document AI functions. In particular,
  **`ai_prep_search` is a beta feature requiring Runtime 18.2 or newer or
  compatible serverless support**. A serverless environment supporting VARIANT
  is also required. A workspace with `ai_parse_document` does not necessarily
  have `ai_prep_search` enabled. The deployment must pass this capability check;
  do not silently substitute a different chunking method.

These resources incur Databricks and model-inference charges. The first run also
prepares the search index, so allow time for managed services to start.

A workspace admin must enable **AI Prep Search** in **Settings → Previews**.
The setup script checks this before starting expensive document processing.
An admin can inspect the setting through the CLI:

```bash
databricks workspace-settings-v2 get-public-workspace-setting ai_prep_search --profile YOUR_PROFILE
```

## 1. Get the code and install dependencies

```bash
git clone https://github.com/dan-keeling-databricks/databricks-agentic-rag.git
cd databricks-agentic-rag
uv venv --python 3.11
source .venv/bin/activate
uv pip install -r requirements.txt
```

The command examples in this guide use macOS/Linux shell syntax. On Windows,
activate `.venv\Scripts\Activate.ps1` from PowerShell instead. Put commands shown
across multiple lines on a single line, removing the trailing backslashes.

## 2. Choose and check your workspace

List your existing logins:

```bash
databricks auth profiles
```

Choose the profile pointing to your intended workspace. This guide uses
`YOUR_PROFILE` as a placeholder; replace it in every command. If you need a new
login, use your workspace URL and a profile name of your choice:

```bash
databricks auth login --host https://YOUR_WORKSPACE_HOST --profile YOUR_PROFILE
databricks current-user me --profile YOUR_PROFILE
```

Do not copy credentials into the source code. The CLI and app use Databricks
authentication.

Find a warehouse you can use:

```bash
databricks warehouses list --profile YOUR_PROFILE
```

Copy its ID. Choose the existing catalog where this solution should live; the
default dedicated schema is `agentic_rag`. Use a separate schema for this
reference implementation so its resources are easy to find and clean up.

## 3. Deploy and load the sample

Replace all three placeholder values:

```bash
python scripts/deploy.py \
  --profile YOUR_PROFILE \
  --catalog YOUR_CATALOG \
  --warehouse-id YOUR_WAREHOUSE_ID
```

The setup command writes local bundle variable overrides, deploys the resources,
downloads the pinned sample PDFs into the volume, runs the ingestion job to
prepare documents and create/synchronize the search index, grants the app's
identity the required access, and starts the app. Keep the local overrides when
running the follow-on commands below. They contain deployment settings, not
credentials, and are kept out of Git.

Use `python scripts/deploy.py --help` for supported options. To start with your
own documents rather than the sample corpus, pass `--skip-sample-data`. If the
volume is empty, setup creates the infrastructure and prints its upload location.
Upload PDFs there through Catalog Explorer, then rerun the same setup command
with `--skip-sample-data` to finish ingestion, permissions, and app startup.

If setup reports an unsupported AI function, unavailable model, or permission
error, resolve that prerequisite before proceeding. Check the failed pipeline
update or job task for the full error message. Resource creation alone is not
evidence that the document-processing path works.

## 4. Open the app and ask a question

Open the app URL printed by setup. You can also find the app in your workspace's
**Compute → Apps** area. Sign in with an identity that has permission to use it.

Try:

> According to the ingestion ebook, what is Auto Loader used for?

Then ask a follow-up:

> How does that compare with COPY INTO?

Check the cited source passages and page references. The page numbers are
physical PDF pages, which can differ from page numbers printed in the document.
The architecture tab links to the solution's actual deployed components.

Open **Agent activity** to see the agent's actual LangGraph diagram: plan a
search, search the documents, assess the evidence, and respond, with a return to
search when more evidence is needed. Select a saved run to inspect its timestamp
and recorded steps, including search queries, retrieved passages, model call
inputs and outputs, and saved decisions. Refresh the recent-runs list after a
new question; trace ingestion can take a short time. Use the MLflow link to open
the full saved trace.

Activity history is shared: every authorized app user can inspect these traces
from the configured experiment, including other users' questions and document
excerpts. The chat itself remains session-based. Review this access model before
using sensitive questions or PDFs.

## 5. Set up and run evaluation

Run this explicit setup once after deployment and ingestion:

```bash
databricks bundle run setup_evaluation -t demo --profile YOUR_PROFILE
```

It seeds the managed `YOUR_CATALOG.agentic_rag.evaluation_questions` dataset and
registers the scoring definitions in the existing MLflow experiment. Substitute
your chosen schema if you changed the default. Open the experiment from the
Architecture tab and inspect its **Datasets** and **Scorers** areas.

The repository's `evaluation/benchmark.jsonl` is only the starter question set.
After setup, maintain questions and reference answers in the managed dataset.
Normal benchmark runs do not overwrite your edits or register new scorer versions.
Rerunning setup preserves an existing dataset and publishes scorer versions;
use it deliberately after changing scorer definitions.

Then run an evaluation:

```bash
databricks bundle run evaluate_agent -t demo --profile YOUR_PROFILE
```

The job runs `notebooks/evaluate_agent.py`: it loads the managed dataset and
registered scorers, calls the same agent as the app, and evaluates it with
`mlflow.genai.evaluate()`. Open the native evaluation run in the MLflow experiment.
Review both the overall results and individual questions:
expected answer, generated answer, judge reasoning, retrieved passages, timing,
and trace. A high average can hide a poor answer to an important question.

For the native UI workflow, choose **Run evaluation → Use code** and use the
deployed notebook for these custom scoring functions. **Select traces** can
rescore existing answers when their reference expectations are available.

The initial 20 questions cover factual lookup, combining documents, follow-ups,
and insufficient-evidence cases. Reference answers come from the sample PDFs and
need customer review before being treated as approved truth. Quality thresholds
are optional and unset by default. Review failures, fix defects, and use the
measured baseline to compare your changes.

Evaluation calls models and incurs inference charges each time it runs.

## Add your own PDFs

1. In Catalog Explorer, open your deployment's catalog and `agentic_rag` schema.
   Open the PDF landing volume linked from the Architecture tab.
2. Upload new PDFs. For this reference implementation, give each new document a
   new filename; replacement and deletion require additional handling.
3. Run:

   ```bash
   databricks bundle run ingest_documents -t demo --profile YOUR_PROFILE
   ```

4. Inspect `document_processing_status` in Catalog Explorer. Confirm your files
   are ready and the search index update completed before asking about them.
5. Add representative questions and reviewed answers to the managed MLflow
   dataset, then rerun evaluation. The starter questions remain specific to the
   sample documents. See [evaluation](EVALUATION.md) for reference-field formats.

See [the pipeline guide](PIPELINE.md) for the saved stages, failure statuses, and
reprocessing guidance.

## If something goes wrong

| What you see | What to check |
| --- | --- |
| Login or permission error | Check the explicit CLI profile, resource permissions, and app service principal grants. |
| `ai_prep_search` not found | Check feature enablement and the actual pipeline runtime/channel; support in another warehouse or notebook is not sufficient. |
| Pipeline has failed documents | Inspect `document_processing_status` and the saved raw AI error details. |
| App finds no passages | Confirm files were ingested, searchable chunks exist, and the index synchronization completed. |
| App cannot call the model | Check the configured gateway route/model endpoint and its permissions for the app identity. |
| No traces appear | Check the configured MLflow experiment and write permission for the app/job identity. |
| An answer is incorrect | Inspect its sources and trace; compare retrieval failures with answer-generation failures before changing settings. |

## Remove a test deployment

Review the target, profile, and resources before running:

```bash
databricks bundle destroy -t demo --profile YOUR_PROFILE
```

This is destructive. Bundle-managed resources can be deleted, and associated
data may be lost. Save any PDFs, results, or traces you want to keep first.
Check Catalog Explorer and AI Search afterward for data or resources deliberately
retained by the deployment or created by setup tasks. Never delete a shared
catalog to clean up this example.

Read [operational hardening](HARDENING.md) before adapting the example for a
production service.
