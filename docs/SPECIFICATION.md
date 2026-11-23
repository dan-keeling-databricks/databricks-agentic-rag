# Databricks agentic document RAG — specification

Status: specification agreed; implementation and workspace capability validation
in progress.
Created: 2026-11-23.

This file is the durable source of truth for this project. Requirements recorded
from the initial request are distinguished from proposals awaiting discussion.
Update this file after each clarification section. Do not treat a recommendation
or an unanswered question as agreement.

## Goal

Deliver an end-to-end, customer-adoptable unstructured document RAG solution on
Databricks. Prioritize readability, excellent documentation, simple operation,
minimal complexity, and configuration without workspace-specific code changes.
Implement, validate, and deploy after the specification is agreed.

## Requirements from the initial request

| ID | Independent requirement | Interpretation |
| --- | --- | --- |
| R1 | Customer handover | Produce readable source, configuration, and thorough setup and operational documentation suitable for sharing with a customer. |
| R2 | PDF landing | Assume the customer's source corpus consists of PDFs, landing in a Unity Catalog volume. |
| R3 | Incremental ingestion | Use Auto Loader within a Databricks pipeline to ingest the landed files. |
| R4 | Document preparation | Use Databricks AI functions, including document parsing, search preparation, and structured extraction. Interpret the dictated names as `ai_parse_document`, `ai_prep_search`, and `ai_extract`, subject to workspace capability verification. |
| R5 | Search | Publish prepared content to a Databricks AI Search index, formerly called Vector Search. |
| R6 | Agent | Host a LangGraph agent in a simple Databricks App to answer user questions through agentic RAG. |
| R7 | Tracing | Use MLflow for agent tracing. |
| R8 | Evaluation | Use MLflow to benchmark behavior against questions and approved answers and support comparison of pipeline or agent configurations. |
| R9 | Architecture tab | Explain the complete implemented flow in the app and link to the actual deployed Databricks components. |
| R10 | Initial deployment | Deploy into the user's Azure Classic Stable workspace; exact CLI profile and host remain to be confirmed. |
| R11 | Portability | Avoid hard-coded workspace identifiers; make customer adoption from GitHub straightforward. GitHub repository creation/publication destination remains unspecified. |
| R12 | Delivery process | Clarify ambiguities section by section, record agreed decisions durably, then implement, validate, and deploy. |

## Agreed architecture

PDFs in UC volume -> Auto Loader -> Lakeflow Spark Declarative Pipeline ->
persisted document parsing and metadata extraction -> search-ready chunks ->
Delta Sync AI Search index -> LangGraph retrieval and answer generation in a
Databricks App. MLflow captures agent traces and benchmark evaluation runs.
The app includes chat and architecture tabs.

Proposed engineering conventions: configuration-driven deployment, a small
repository, reproducible resource definitions, and separate customer-neutral
examples from local deployment settings. Streamlit and on-demand ingestion are
agreed. Compute type, endpoint type, models, and resource names remain open.

## Clarification sequence

### 1. Intended use, corpus, and boundaries — AGREED

Agreed decisions:
- Deliver a working reference implementation. Optimize for ease of use,
  readability, and helping the customer understand the solution before they
  undertake operational hardening themselves.
- Include concrete notes explaining recommended operational hardening; that
  hardening is outside implementation scope unless subsequently agreed.
- Answer questions over PDFs and metadata extracted from those PDFs only.
  Existing structured business tables are outside scope.
- The user will provide a link to the source documents. Do not substitute a
  synthetic corpus for the agreed validation corpus.
- Analyze a selection of those documents and author a benchmark with questions,
  expected answers, and source evidence. Label these as reference answers derived
  by the implementation author, pending review, rather than customer-approved
  answers. Preserve a route to replace or approve them for customer use.

Source-document link received:
https://github.com/databricks-demos/dbdemos-dataset/tree/main/llm/databricks-pdf-documentation

### 2. Ingestion and document preparation — AGREED

Agreed decisions:
- Customer sizing assumption: 1,000 PDFs. This is a design assumption, not a claim
  that this session will load-test 1,000 documents.
- Use the linked public dbdemos dataset for the demonstration and benchmark.
  The GitHub contents API lists 29 PDFs and a NOTICE file as of inspection.
- New PDFs land in a Unity Catalog volume; an on-demand pipeline run ingests
  new files and prepares them for search. No automated schedule is required.
- Replacement/deletion handling is an operational-hardening extension to document,
  outside the reference implementation's ingestion behavior.
- No specific extraction fields are required; select a small, understandable
  schema appropriate to the corpus.

Implementation choices under that scope:
- Use `ai_extract` for title, short summary, and topics. Keep the extraction
  schema configurable so customers can substitute their own fields.
- Capture source path, filename, document identity, file size, ingestion time,
  and page/chunk provenance deterministically rather than asking an LLM to
  infer operational metadata. Derive page counts from parsed document structure.
- Retain processing status and error details for failed documents so omissions
  are visible. Document retry/reprocessing steps during implementation.
- Preserve source/NOTICE information and record a reproducible dataset revision
  when preparing the sample corpus.

Read-only sample inspection performed with pypdf: the LLM compact guide (9 pages),
ingestion ebook (16 pages), and digital twin ebook (16 pages) each contain an
extractable text layer. This does not establish scan/layout characteristics for
all 29 PDFs. Downloaded samples and extracted text are local intermediate files
under `tmp/pdfs/`; they are not authored benchmark answers or application code.

### 3. Search and agent behavior — AGREED

Agreed decisions:
- Implement a small LangGraph flow that searches, assesses retrieved evidence,
  and can refine its query and search again.
- Default to at most three searches per user turn, with a configurable limit.
  Bound the graph execution as well as retrieval calls so the agent terminates.
- Support answers that synthesize evidence across multiple documents.
- Include document and page citations backed by retrieved source provenance.
- Explicitly acknowledge insufficient evidence when the documents do not support
  an answer; do not fill evidence gaps from model knowledge.
- Support follow-up questions using context from the current chat session.
- Persistent chat history is outside the reference implementation scope; describe
  it as a hardening extension.

Model/embedding endpoint selection and workspace capabilities will be resolved
in section 6. Keep retrieval parameters configurable; no separate structured-data
query engine is required by the agreed PDF-only scope.

### 4. App experience and access — AGREED

Agreed decisions:
- Build the Databricks App with Python and Streamlit to minimize code and make
  the reference implementation easy to understand.
- Provide Chat and Architecture tabs. Chat supports session follow-ups and cited
  answers; Architecture explains the actual deployed flow and links to its
  Databricks components.
- All authorized app users search the same shared document collection. Describe
  per-document authorization as a hardening extension.
- Upload PDFs through the Databricks volume interface, rather than an app upload
  feature.
- Run ingestion and evaluation through documented Databricks jobs, rather than
  app controls.
- No persistent application database is required by the agreed features.

### 5. MLflow tracing, evaluation, and acceptance — AGREED

Agreed decisions:
- Author an initial 20-question benchmark covering factual lookup,
  multi-document synthesis, follow-up questions, and questions the corpus cannot
  answer. Include expected answers and document/page evidence where applicable.
- Measure answer correctness, groundedness, citation validity, retrieval quality,
  and response latency. Capture retrieval calls and model interactions in MLflow
  traces.
- Use AI judges for semantic evaluation, including correctness and groundedness.
  Complement judges with deterministic checks for reference validity and timing.
  Judge assessments are measurements, not human approval of the benchmark.

Agreed evaluation reporting and acceptance:
- Record an actual measured baseline in MLflow with per-question results,
  aggregate metrics, judge rationales, traces, and configuration/version context.
- Produce a concise durable evaluation summary linking to the run, describing
  failures and limitations and explaining how to rerun and compare configurations.
- Provide configurable quality thresholds without inventing a customer quality
  target; require successful functional end-to-end validation for deployment.
- Review benchmark failures and fix clear implementation defects before handover.
  Document remaining quality limitations. No numerical answer-quality deployment
  gate is required for this initial reference implementation.

Dataset format, exact scorers, judge endpoint, and trace data handling remain to
resolve through design and deployment configuration. Benchmark reference answers
authored from the source PDFs must remain labelled pending customer review.

### 6. Deployment and portability — AGREED

Agreed decisions:
- Explicitly selected CLI profile: `classic-stable-dankeeling-azure`.
- Target workspace: `https://adb-7405617409436848.8.azuredatabricks.net`.
- Unity Catalog catalog: `classic_stable_dankeeling`.
- Use a Databricks Declarative Automation Bundle for deployment with portable,
  configurable resource names and endpoint settings.
- Prefer open-weight models served through Unity AI Gateway (user wording:
  "Unity Gateway") and serverless compute wherever supported. Verify the precise
  gateway API and available model routes before selecting endpoints. Document any
  platform-managed AI function model choices separately from configurable agent,
  embedding, and judge model choices.
- No spending constraints were specified.
- Prepare a repository locally, then push it to the `dan-keeling-databricks`
  GitHub account as private repository `databricks-agentic-rag`.

Proposed implementation default: a dedicated `agentic_rag` schema in the selected
catalog. Read-only inspection found no schema with that name. Keep it configurable.
Keep target-specific deployment settings separate from customer-neutral examples.
Workspace capability checks are in progress; no resources have been created.

### 7. Documentation and final acceptance — AGREED

Deliver documentation covering quickstart, architecture and data contracts,
configuration, customer deployment, evaluation and benchmark results, operations,
permissions, troubleshooting, costs, cleanup, and operational hardening.
The README must be especially understandable, use plain language where possible,
and link to a step-by-step deployment quickstart.

Final validation must demonstrate PDF ingestion through all three AI functions,
index synchronization, cited chat and session follow-ups, MLflow traces, and the
20-question evaluation. Record actual results and limitations.

Create private GitHub repository `dan-keeling-databricks/databricks-agentic-rag`
and push the local project. User explicitly requested a delivery goal and an agent
execution team; goal created and pipeline, app, and evaluation agents assigned.

## Technical verification backlog

- Verify current official APIs and actual Azure workspace support for all three
  document AI functions before committing to a runtime/compute design.
- The installed AI-functions skill describes `ai_prep_search` as requiring
  DBR 18.2+ or supported serverless environment; this is guidance to verify,
  not evidence of availability in the target workspace.
- Preserve source provenance through parsing, extraction, chunking, retrieval,
  and citations; choose stable unique chunk keys across documents.
- Verify app identity permissions for index queries, model calls, MLflow, and
  any document access. Agree access behavior before implementing it.
- Define validation that exercises real ingestion, indexing, agent execution,
  tracing, evaluation, and deployed UI behavior.
- Use explicit user-selected profiles for all CLI operations. Do not read or
  pass bare API tokens.

## Decision log

| Date | Section | Decision | State |
| --- | --- | --- | --- |
| 2026-11-23 | Initial request | R1–R12 transcribed and grouped above. | User-stated requirements; interpretation awaiting review |
| 2026-11-23 | 1 | Scope/corpus questions prepared. | Resolved by subsequent decisions |
| 2026-11-23 | 1 | Reference implementation emphasizing simplicity; include operational hardening guidance for customer follow-on work. | Agreed |
| 2026-11-23 | 1 | PDFs and extracted metadata only; no existing structured business tables. | Agreed |
| 2026-11-23 | 1 | User provides document link; author benchmark from analysis of selected documents, with source evidence and review status. | Agreed; source link received |
| 2026-11-23 | 2 | Public dbdemos PDF corpus; customer sizing assumption of 1,000 PDFs. | Agreed |
| 2026-11-23 | 2 | New files in volume and on-demand pipeline runs; document replacement/deletion as hardening extensions. | Agreed |
| 2026-11-23 | 2 | No prescribed metadata fields; choose a simple schema appropriate to the documents. | Agreed; selected title, summary, topics as implementation defaults |
| 2026-11-23 | 3 | LangGraph search/evidence assessment/query refinement loop; maximum three searches per turn by default, configurable; multi-document synthesis. | Agreed |
| 2026-11-23 | 3 | Document and page citations; explicit insufficient-evidence responses. | Agreed |
| 2026-11-23 | 3 | Follow-up questions within the current chat session; persistent chat history documented as an extension. | Agreed |
| 2026-11-23 | 4 | Python/Streamlit app with Chat and Architecture tabs. | Agreed |
| 2026-11-23 | 4 | Shared corpus for authorized app users; per-document authorization covered in hardening guidance. | Agreed |
| 2026-11-23 | 4 | Upload via Databricks volumes; run ingestion/evaluation via documented jobs, without app controls. | Agreed |
| 2026-11-23 | 5 | Initial 20-question benchmark covering lookup, synthesis, follow-ups, and unanswerable questions, with expected answers and evidence. | Agreed |
| 2026-11-23 | 5 | Correctness, groundedness, citation validity, retrieval quality, latency, and MLflow traces; use AI judges for semantic assessment. | Agreed |
| 2026-11-23 | 5 | Measured baseline in MLflow plus a durable evaluation summary; fix clear defects, document remaining limitations, provide configurable thresholds without a numerical deployment gate. | Agreed |
| 2026-11-23 | 6 | Profile classic-stable-dankeeling-azure; workspace adb-7405617409436848.8.azuredatabricks.net; catalog classic_stable_dankeeling. | Agreed |
| 2026-11-23 | 6 | Bundle deployment; prefer open-weight models through Unity Gateway and serverless compute where possible; no spending constraints. | Agreed; gateway API and model availability to verify |
| 2026-11-23 | 6 | Prepare locally then push to dan-keeling-databricks/databricks-agentic-rag, initially private. | Agreed |
| 2026-11-23 | 7 | Plain-language README, deployment quickstart, full handover documentation and actual end-to-end validation. | Agreed |
| 2026-11-23 | Execution | Create an explicit delivery goal and agent execution team before proceeding. | Done |

## Implementation and deployment status

Implementation completed across pipeline, app, and evaluation workstreams;
integration and live validation are in progress. The primary agent owns the
bundle, deployment, validation, and repository publication.

Created dedicated document and trace schemas, source volume, serverless pipeline,
AI Search endpoint, MLflow experiment, jobs, Streamlit App, and two governed model
services. The agent service uses GPT OSS 120B and the independent judge service
uses Llama 3.3 70B. Both custom routes passed a real test request through Unity AI
Gateway. AI Search uses a managed GTE embedding endpoint. AI function models
remain platform-managed.

Strict bundle validation and 30 local checks pass. All 29 pinned sample PDFs were
uploaded; Auto Loader completed its first ingestion. The first AI preparation run
is still processing, so no successful search/agent/evaluation baseline is claimed
yet. The SQL warehouse did not expose ai_prep_search; the serverless PREVIEW
pipeline accepted the graph and is being verified through actual execution.

Private GitHub repository created at
https://github.com/dan-keeling-databricks/databricks-agentic-rag . Final tested code
and validation evidence have not yet been pushed.
