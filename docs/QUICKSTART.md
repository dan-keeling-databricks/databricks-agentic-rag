# Deploy the PDF assistant

This guide deploys your own copy of the solution. You will choose a workspace,
create its resources, load sample PDFs, and open the app. Nothing needs to be
deployed into the original author's workspace.

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
  and AI Search resources, and to grant the app's service principal access to
  the resources it needs.
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

The environment activation command above is for macOS/Linux shells. On Windows,
activate `.venv\Scripts\Activate.ps1` from PowerShell instead.

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

## 5. Run the benchmark

```bash
databricks bundle run evaluate_agent -t demo --profile YOUR_PROFILE
```

Open the evaluation job run and the MLflow experiment linked from the app's
Architecture tab. Review both the overall results and individual questions:
expected answer, generated answer, judge reasoning, retrieved passages, timing,
and trace. A high average can hide a poor answer to an important question.

The initial 20 questions cover factual lookup, combining documents, follow-ups,
and insufficient-evidence cases. Reference answers come from the sample PDFs and
need customer review before being treated as approved truth. There is no fixed
quality score that blocks this initial reference deployment. Review failures,
fix defects, and use the measured baseline to compare your changes.

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
5. Add representative questions and reviewed answers to your own benchmark,
   then rerun evaluation. The supplied benchmark remains specific to its sample
   documents.

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
