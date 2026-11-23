# Configuration guide

You should not need to edit Python code to move the solution to a new workspace.
Use a Databricks CLI profile to select the workspace, bundle variables to name
the resources, and environment settings to adjust the running agent.

Start with the [deployment quickstart](QUICKSTART.md). This page explains the
settings after you understand the deployment steps.

## Deployment settings

`scripts/deploy.py` accepts the following options. Values are saved locally in
`.databricks/bundle/demo/variable-overrides.json`; that file is not committed.

| Option | Meaning | Default |
| --- | --- | --- |
| `--profile` | Your explicitly chosen Databricks CLI authentication profile. | Required |
| `--catalog` | An existing Unity Catalog catalog where the solution can create schemas. | Required |
| `--warehouse-id` | A usable SQL warehouse for reading MLflow's stored traces; serverless is preferred. | Required |
| `--schema` | Dedicated schema for documents, model services and the search index. | `agentic_rag` |
| `--app-name` | Workspace-unique Databricks App name. | `agentic-pdf-rag` |
| `--search-endpoint` | Name of the managed AI Search endpoint. | `agentic-pdf-rag-search` |
| `--skip-sample-data` | Do not upload the public example corpus. Land your own PDFs before ingestion. | Off |

The bundle uses target `demo`. It also creates `<schema>_traces` for MLflow trace
storage. Choose a dedicated schema so that this reference's resources are easy
to identify and clean up.

### Advanced bundle variables

The variables are declared in [databricks.yml](../databricks.yml). Put overrides
in `.databricks/bundle/demo/variable-overrides.json`, alongside the values saved
by the deployment script. The script preserves existing advanced overrides.

| Variable | Meaning | Default |
| --- | --- | --- |
| `agent_model` | Underlying foundation model behind the `agent_model` Unity Gateway service. | `system.ai.gpt-oss-120b` |
| `judge_model` | Underlying model behind the independent `judge_model` service. | `system.ai.llama_v3_3_70b_instruct` |
| `embedding_endpoint` | Model-serving endpoint used by AI Search to represent text numerically. | `databricks-gte-large-en` |
| `pipeline_channel` | Pipeline release channel. The selected environment must support every document AI function. | `PREVIEW` |

Use actual model names available in your workspace. Model availability and access
can differ across workspaces. Model service names passed to the application are
fully qualified Unity Catalog names, for example
`your_catalog.agentic_rag.agent_model`; underlying model names are configured in
the bundle. An embedding endpoint is configured separately from those services.

## Agent and app settings

The bundle supplies the core deployment settings in
[resources/app.app.yml](../resources/app.app.yml). Optional agent settings, such
as `MAX_SEARCHES` and `RETRIEVAL_K`, use the defaults below unless you add them to
the app's `config.env` section and redeploy. The evaluation job sets its own
`JUDGE_ENDPOINT`; it is not needed by the chat app. If you change agent settings,
apply the same settings to the evaluation job when comparing its results.

For local use, set variables in your shell and authenticate with your chosen CLI
profile. Never put credentials in a configuration file committed to Git.

| Variable | Meaning | Default |
| --- | --- | --- |
| `AGENT_ENDPOINT` | Unity Gateway model-service name used to plan, assess and answer. | Required |
| `VECTOR_SEARCH_INDEX` | Fully qualified AI Search index name: `catalog.schema.index`. | Required |
| `MLFLOW_EXPERIMENT_ID` | Deployed MLflow experiment for agent traces and evaluation. | Required to run the agent |
| `USE_AI_GATEWAY` | Route model calls through Unity Gateway. Set `false` only when intentionally using a model-serving endpoint instead. | `true` |
| `AI_GATEWAY_BASE_URL` | Optional explicit URL for a supported gateway deployment. Normally leave unset; the application uses your workspace's Unity Gateway URL. | Unset |
| `MAX_SEARCHES` | Maximum searches per question; must be between 1 and 10. | `3` |
| `RETRIEVAL_K` | Maximum passages returned per search; must be between 1 and 50. | `6` |
| `MAX_CONTEXT_CHARACTERS` | Total retrieved-text characters allowed in an agent prompt. Complete passages that exceed the remaining budget are omitted. | `48000` |
| `MAX_HISTORY_MESSAGES` | Recent user/assistant messages passed for follow-up questions. Set `0` to omit chat context. | `12` |
| `JUDGE_ENDPOINT` | Model-service name used by evaluation judges. | Agent endpoint when unset locally; bundle evaluation uses a separate judge service |

MLflow uses `MLFLOW_TRACKING_URI`, defaulting to `databricks`. When running locally
with a named profile, use `databricks://YOUR_PROFILE` and set
`DATABRICKS_CONFIG_PROFILE=YOUR_PROFILE` for SDK clients. The deployed app uses its
automatically provided service identity; it does not need a personal token.

The runtime uses the pinned Databricks SDK and OpenAI client directly, with plain
MLflow. The SDK keeps authentication refreshed while the application points its
model client at the workspace's Unity Gateway route. This deliberately avoids
the current `databricks-openai` package's local Spark/Databricks Connect dependency
chain inside serverless jobs. The SDK factory is deprecated but supported by the
pinned version; a future lean replacement can be adopted after compatibility
testing. This does not change model access or require managing tokens yourself.

The serverless evaluation job installs `mlflow-skinny` at the same pinned MLflow
version. It includes GenAI evaluation and tracing while omitting unrelated model
training and web-server packages. The app/local requirements use the full MLflow
distribution; agent behavior, scorers, prompts, and MLflow API versions are shared.

`MLFLOW_TRACING_SQL_WAREHOUSE_ID` identifies the warehouse used to read Unity
Catalog traces. The bundle supplies it and grants the app's identity warehouse
access. The experiment is bound to its trace schema during deployment; changing
an environment variable is not a migration of an existing experiment's storage.

### Architecture links and startup

| Variable | Meaning |
| --- | --- |
| `DATABRICKS_HOST` | Workspace URL. Databricks Apps provides this automatically. |
| `SOURCE_VOLUME` | Landing volume, as `/Volumes/catalog/schema/volume` or `catalog.schema.volume`. |
| `PIPELINE_ID` | Document-processing pipeline ID. |
| `INGESTION_JOB_ID` | Job that runs processing and synchronizes the index. |
| `EVALUATION_JOB_ID` | Benchmark evaluation job ID. |
| `REPOSITORY_URL` | Optional link to your copy of the source repository. |
| `DATABRICKS_APP_PORT` | Port assigned by Databricks Apps. `run_app.py` reads it; local default is `8000`. |

Resource IDs used for links come from the bundle, rather than being copied into
the application. Missing optional link settings simply omit those links.
`app.yaml` also disables Streamlit's CORS/XSRF checks for the Databricks Apps
reverse proxy and disables usage telemetry. Databricks handles workspace sign-in
and app access; keep the app behind that managed access layer.

## PDF preparation settings

The pipeline reads `rag.source_volume` from its Spark configuration. The bundle
sets it to the deployed landing volume. It also accepts
`rag.extraction_schema` to change the fields requested from `ai_extract`; see
[PDF pipeline](PIPELINE.md) for its format and outputs.

Changing extraction logic or chunk preparation can change stored content and
search results. Follow the reprocessing steps, refresh the index, and rerun the
benchmark before comparing the new behavior. Replacing or deleting PDFs in
place is outside the append-only reference ingestion contract.
