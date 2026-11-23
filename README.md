# Ask questions of your PDFs on Databricks

This is a small, working reference implementation that turns a folder of PDFs
into a question-answering assistant. It is designed to help you understand the
moving parts, deploy your own copy, and then adapt it to your documents.

The assistant finds relevant passages, uses them to write an answer, and shows
which documents and pages support that answer. You can ask follow-up questions
in the same chat. If the documents do not provide enough evidence, the assistant
should say so.

**Start here: [deployment quickstart](docs/QUICKSTART.md).** It walks through the
prerequisites, deployment, your first question, and the benchmark.

## How it works

1. **Put PDFs in a volume.** A Unity Catalog volume is a governed folder in
   Databricks. The sample loader can fill it with public example documents.
2. **Read and prepare them.** An on-demand job uses Auto Loader to pick up new
   files. Three built-in AI functions read the pages (`ai_parse_document`),
   prepare searchable passages (`ai_prep_search`), and extract a title, short
   summary, and topics (`ai_extract`). Their results are saved as tables.
3. **Make the passages searchable.** Databricks AI Search, formerly called
   Vector Search, builds an index that can find passages by meaning as well as
   keywords.
4. **Ask the assistant.** A Streamlit app hosts a small LangGraph agent. For each
   question, it searches, checks whether the evidence is enough, and can refine
   its search. It makes at most three searches by default, then answers with
   document/page citations or acknowledges missing evidence.
5. **Inspect and measure it.** MLflow records traces: the steps, model calls,
   searches, and timings behind an answer. A separate evaluation job runs a
   20-question benchmark and uses AI judges to help assess answer quality.

This approach is often called **retrieval-augmented generation**, or **RAG**:
find useful source material first, then ask the model to answer using it.
“Agentic” means the assistant can decide to improve its search before answering.

## What you get

- A **Chat** tab with source passages, page references, follow-up questions, and
  links to traces when available.
- An **Agent activity** tab with a diagram of the actual LangGraph steps and a
  history of saved runs. Pick a run to inspect its timestamp, searches, model
  call inputs and outputs, and recorded decisions; refresh the list to find newer
  runs, or open the full trace in MLflow.
- An **Architecture** tab explaining the deployed flow, with links to its volume,
  tables, pipeline, search index, jobs, and MLflow experiment.
- A portable **Databricks bundle**: a set of configuration files that creates the
  solution's resources in your own workspace.
- A fixed version of public sample PDFs, test questions with answers checked
  against those documents, and instructions for comparing changes using MLflow.
- Notes on what to change before operating this as a production service.

The sample contains **29 public Databricks PDFs**. Larger collections need
separate performance and capacity testing.

## Deploy your own copy

After completing the [quickstart prerequisites](docs/QUICKSTART.md#before-you-start),
the setup command is:

```bash
python scripts/deploy.py \
  --profile YOUR_PROFILE \
  --catalog YOUR_CATALOG \
  --warehouse-id YOUR_WAREHOUSE_ID
```

You choose the workspace through your Databricks CLI profile. Configuration
controls resource names and model endpoints; you do not edit the application
code to change workspaces. The setup command deploys the bundle, loads the sample
PDFs, runs ingestion and index preparation, and starts the app. Evaluation runs
separately so you can repeat it after making a change.

The solution prefers serverless compute and open-weight answer/judge models
through Databricks' gateway. The built-in document AI functions select their own
platform-managed models. Feature and model availability varies by workspace;
see the quickstart before deploying.

## Understand and adapt it

| Read this | To understand |
| --- | --- |
| [Quickstart](docs/QUICKSTART.md) | How to deploy, load documents, ask questions, and run evaluation. |
| [PDF pipeline](docs/PIPELINE.md) | The saved stages, search-table fields, provenance, and processing errors. |
| [Architecture](docs/ARCHITECTURE.md) | What each component does and how the pieces fit together. |
| [Configuration](docs/CONFIGURATION.md) | Settings for your workspace, models, and agent behavior. |
| [Evaluation](docs/EVALUATION.md) | How the benchmark, AI judges, and comparison runs work. |
| [Measured baseline](docs/BASELINE.md) | Actual results from the initial 20-question benchmark, including weaknesses to review. |
| [Validation record](docs/VALIDATION.md) | What was actually checked and any remaining limitations. |
| [Operations](docs/OPERATIONS.md) | Adding documents, checking failures, permissions, costs, and cleanup. |
| [Operational hardening](docs/HARDENING.md) | What to add for production access control, reliability, cost management, and quality assurance. |
| [Agent code](src/rag/agent.py) | How the bounded search-and-answer loop works. |
| [Benchmark questions](evaluation/benchmark.jsonl) | Questions, reference answers, and source evidence used for evaluation. |

The benchmark's reference answers were authored from the sample documents. They
are a starting point for review, rather than customer-approved answers. AI judge
scores are useful measurements, not a guarantee that an answer is correct.

## Scope

All authorized app users search the same shared document collection and can
inspect its shared historical agent traces in **Agent activity**, including
questions, retrieved passages, and model inputs and outputs from other runs.
The tab shows saved steps and explicit decisions, such as whether more evidence
was needed. Interactive chat history lasts for the current session; saved MLflow
traces remain available according to the deployment's retention policy.
Ingestion is on demand and handles new PDFs;
replacement, deletion, persistent conversations, and per-document access rules
are described as follow-on work in the hardening guide.

This is a reference implementation intended to be read and adapted. Before
exposing sensitive documents or relying on answers for important decisions,
review the access, tracing, and quality controls in that guide.
