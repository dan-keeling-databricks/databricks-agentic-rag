# Validation record

The end-to-end PDF pipeline, search, app, follow-up questions, persisted traces,
and native MLflow evaluation have been verified. The current benchmark removes
source-title hints and completed all 20 questions. This file records observed
results. Read [the measured baseline](BASELINE.md) for answer-quality
failures and limitations.

## Environment and source data

- Date: 23 November 2026.
- Initial deployment: Azure Classic Stable, explicitly selected profile
  `classic-stable-dankeeling-azure`, catalog `classic_stable_dankeeling`.
- Document preparation: serverless Lakeflow pipeline, PREVIEW channel.
- Public sample PDFs pinned at source revision
  `1a8743c8fe783b3ac42ab37aa18118387fb3c996`.
- Answer model: GPT OSS 120B; independent judge: Llama 3.3 70B, through separate
  governed Unity AI Gateway model services.
- Embeddings: managed `databricks-gte-large-en` endpoint.
- Trace warehouse: standard Serverless Starter Warehouse. A Lakehouse//RT
  warehouse rejected MLflow annotation edits; the standard warehouse succeeded.

## Observed checks

| Check | Result |
| --- | --- |
| Strict bundle validation | Passed with explicit target and profile. |
| Current local regression suite | 82 passed; three live SQL tests skipped; one third-party SQLAlchemy deprecation warning. The SQL conversion's separate live checks are recorded below. |
| Download integrity | Git blob hashes verified; manifest and NOTICE preserved. |
| Real Gateway model calls | Answer and judge services both passed. |
| PDFs in saved ingestion/parsing/preparation stages | 29 in each stage. |
| Document processing status | All 29 ready; no reported processing/extraction errors. |
| Search-ready chunks | 448 rows; 448 distinct chunk IDs. |
| Missing or invalid page ranges | 0. |
| Source/page spot check | Compact LLM guide chunks/title inspected against the PDF. |
| Search index | Ready; 448 indexed rows. |
| Repeat ingestion and fresh index synchronization | Passed; setup wrapper completed successfully. |
| Streamlit UI | App running; Chat and Architecture tabs rendered in browser. |
| Live cited answer and session follow-up | Both passed against deployed services. |
| Full persisted traces | Both read back from Unity Catalog: 11 spans each, including AGENT, CHAIN, CHAT_MODEL, and RETRIEVER. |
| App's own identity | Real retrieval, model call, cited answer, and persisted trace verified under the app service principal. |
| Native managed benchmark | 20/20 questions completed; 85% correctness; named dataset/version lineage recorded. |
| Persisted native assessments | All 116 applicable assessments verified; no null, missing, duplicate or error feedback. |
| Serverless evaluation notebook | Full 20-question job terminated SUCCESS; native MLflow results saved. |
| Managed setup | Serverless notebook succeeded; repeating setup preserved all 20 saved questions and dataset version 1. |
| Scorer registry | Seven saved definitions; six active metrics; all version 1, with the retrieval judge dependency pinned. |
| Repository | Source and documentation pushed to GitHub; repository is public. |

Verified trace examples:

- [First cited answer](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/traces/a3427cffba2a56f263a969d9104d89d9).
- [Session follow-up](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/traces/c600f0de4fd18126ddce0de18e5d6f57).
- [App service identity](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/traces/2356c3ccbbca03a5e3358a13c7714d21).

## Native MLflow evaluation

[Serverless job run 505897162147458](https://adb-7405617409436848.8.azuredatabricks.net/jobs/924395035538194/runs/505897162147458)
and [MLflow evaluation run e453f577c3ba4d29a972cd3ac767f688](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/evaluation-runs/e453f577c3ba4d29a972cd3ac767f688/details)
both completed successfully. Evaluation read the managed
`classic_stable_dankeeling.agentic_rag.evaluation_questions` dataset at version 1
and used registered scorer versions, calling the same agent as the app.

Native run input lineage identifies the Unity Catalog table, dataset ID and
version, with digest `6e325a7c0eb675802402aa624bc1f110`. The experiment's Datasets
UI showed all 20 editable records; its Scorers UI showed the three native AI
judges and four code definitions, including the N/A-aware retrieval wrapper.

Readback found exactly q01–q20 and all 116 applicable assessments: 20 correctness,
20 groundedness, 18 retrieval quality, 20 citation validity, 18 page recall and
20 latency. All required-fact and evidence JSON strings were preserved. The four
inapplicable retrieval assessments were absent as intended. No assessments were
repaired or overwritten.

Correctness was 85%, groundedness 100%, retrieval quality 94.4%, citation validity
90%, and average reference-page recall 94.4%. Mean agent latency was 11.34 seconds,
median 9.58 seconds, p90 15.77 seconds and maximum 23.34 seconds. Failed answers
and potentially strict judge decisions remain visible; see [the baseline](BASELINE.md).

The standalone runner and custom report generator have been removed. The native
notebooks retrieve managed assets and call `mlflow.genai.evaluate()`. Unit checks
exercise source-only scorer serialization and execution, immutable dependency
versions, dataset preservation, reference/input isolation and N/A behavior.
Strict bundle validation passed. The app deployment succeeded with direct links
to the experiment's Datasets, Scorers and Evaluation runs.

## Historical benchmark evidence

[Run b35c5eb751cb423b8904dbd74f1cbc4a](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/runs/b35c5eb751cb423b8904dbd74f1cbc4a)
completed all 20 questions. Correctness was 80%, groundedness 85%, citation
validity 90%, retrieval quality 94.4%, and reference page recall 100%. Mean agent
latency was 59.0 seconds; median 50.5 seconds; p90 83.0 seconds. These are small-set
measurements, not service guarantees. All answers and judge decisions, including
failures, were retained.

The full shared evaluator ran locally against the real deployed index, models,
and Unity Catalog-backed MLflow experiment. There were no mocked predictions or
judgments. The same agent class is used by the app and serverless evaluation job.
The latter is validated separately below rather than being presented as the
execution environment for this full run.

A final read-only audit matched the 20 captured question trace IDs and all 116
applicable feedback entries: 20 correctness, 20 groundedness, 18 retrieval quality,
20 citation validity, 18 page recall, and 20 latency assessments. All values and
rationales matched the original captured report. Provenance is 58 AI-judge and 58
code assessments. Prediction-validation extra traces were excluded from this
count. Four inapplicable retrieval scores remain N/A, not passing scores.

For the two unanswerable questions, null-score feedback initially caused the
backend to reject the assessment batches. Eight applicable annotations were
restored from the run's existing captured results, preserving values, rationales,
failures, and provenance. Readback verified them. No predictions, judgments, or
aggregate metrics were changed. The fix skips inapplicable annotations and is
covered by regression tests. The run artifacts include an annotation-repair note.

## Earlier evaluation job (historical)

[Serverless job run 841001347486225](https://adb-7405617409436848.8.azuredatabricks.net/jobs/924395035538194/runs/841001347486225)
terminated **SUCCESS**, using `question_limit=1`. It installed the dependencies,
imported the shared agent, queried the deployed services, ran all applicable AI
and code checks, and saved reports as MLflow artifacts. Its
[MLflow run](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/runs/351217b980154f16a97e05cd48329c49)
records 1/1 questions completed, zero missing assessments, and the same benchmark
and implementation fingerprints as the full baseline.

This checks job execution, not answer quality across 20 questions. In this repeat
of q01, retrieval quality and reference-page recall passed, but the assistant
abstained and failed correctness/citation checks. This reinforces the observed
conservative-abstention weakness and variation between model calls, even with
temperature set to zero. The job's successful status does not mean every answer
passed; no numerical quality gate was configured. The full measured baseline
above remains a separate 20-question run.

## Deployment compatibility fixes

AI Prep Search Preview was initially disabled. Enabling the documented
`ai_prep_search` workspace setting and starting a fresh pipeline update resolved
that prerequisite; saved parsed PDFs were reused. Setup now checks this before
processing documents.

The serverless evaluation task uses environment 2 (Python 3.11) and the pinned
MLflow SDK distribution. Removing the unnecessary Databricks OpenAI integration
package avoids pulling a local Databricks Connect dependency into this API-only
job. The SDK supplies refreshing authentication to the OpenAI client; no bare
tokens are read or passed. Normal app startup is `python run_app.py`; its identity
diagnostic is not enabled in the final app configuration.

Other real-service checks exposed and resolved these compatibility details:

- Gateway JSON mode requires a literal lowercase `json` instruction in the user
  message.
- AI Search can return integer page columns as floats. Exact finite positive
  whole numbers are accepted; fractions and invalid references are rejected.
- Unity Catalog span values can be JSON-encoded strings; smoke verification
  decodes them and checks actual evidence content.
- Databricks Apps can supply a bare workspace hostname; links normalize to HTTPS.
- Permission updates require a string securable type.
- SQL validation explicitly requests inline JSON because default Arrow responses
  do not populate `data_array`.

## Limits

Validation used the 29-document sample; no 1,000-document or concurrent-user
load test was performed. The question set uses three sample PDFs and awaits
customer review. Missing diagram labels, wrong-entity answers, conservative
abstention, and judge inconsistencies were observed. Page recall and valid
citations alone do not prove useful or correct answers. These limitations are
explained with individual examples in [BASELINE.md](BASELINE.md).


## Agent activity extension

The third app tab was added and verified on 23 November 2026. It reads topology
from the actual compiled LangGraph and lets authorized app users browse shared
past answer traces from this deployment's experiment. The selector supports
24-hour, 7-day, and 30-day windows. Each refresh inspects at most 100 recent trace
metadata records and displays up to 30 matching agent requests. This bounded
recent-history view is not an exhaustive archive browser.

A real browser session against the deployed app loaded 30 previous requests
through the app's service identity, displayed the compiled graph with per-node
visit counts and a recorded 20-operation trace, and showed the saved standalone
search query when the planning step was selected. The trace details include
model calls, retrieval results, evidence decisions, router outputs, final output,
timestamps, durations, and errors where recorded. A link opens the full trace in
MLflow. Parent-child lines show nesting; operation numbers follow start time.

The local Streamlit integration check also loaded a real persisted trace and
selected its planning and final steps. Backend checks verified that model and
retrieval spans inherit their enclosing graph node. Loading historical activity
made no answer-model calls. Activity inspection reads the persisted trace data and compiled graph without
changing answer generation.

Trace-viewer coverage includes the compiled topology,
loop branch, Unicode/quoted graph labels, JSON-encoded UC values,
experiment scoping, parent-child relationships, step selection, empty history,
filtering, and successful loads followed by failed refreshes. Failed refreshes
clear stale history and preserve the graph. The applied history window is shown
explicitly. Source files compile with the Apps Python 3.11 environment.

Shared visibility includes other users' saved questions and document passages.
The app explains this, and the operations and hardening guides describe how to
restrict or redact it before introducing sensitive data.


## SQL document pipeline

The document pipeline is defined in [documents.sql](../src/pipeline/documents.sql)
as four streaming tables and one materialized view. The bundle points to the SQL
file and binds the `source_volume` and `extraction_schema` named parameters.

Validation completed on 23 November 2026:

- All **78 tests passed**, including three live SQL contract tests. The status
  checks exercised 11 synthetic examples covering empty/oversized PDFs, missing
  parsing/preparation results, AI errors, missing extraction, and empty error
  representations.
- SQL projections of all 448 saved search rows and all 29 processing-status rows
  matched the existing data in both directions, with no extra or missing rows.
- An isolated serverless SQL pipeline processed a real sample PDF through
  `ai_parse_document`, `ai_prep_search`, and `ai_extract`: one ready document,
  four unique chunks, and zero invalid page ranges. Its temporary resources
  were removed after testing.
- [Ingestion job run 463023579284984](https://adb-7405617409436848.8.azuredatabricks.net/jobs/1110220157229078/runs/463023579284984)
  completed successfully against the existing pipeline. Update
  `27f72588-5264-4405-a767-dd8f0e688281` completed as a normal incremental update;
  no full refresh or checkpoint reset was used.
- All five dataset schemas and row counts were preserved. The 29 document IDs,
  448 chunk IDs, and the fingerprint of the complete chunk contents were
  unchanged. Change Data Feed remains enabled.
- The AI Search synchronization completed with **448 indexed rows** and
  `ONLINE_NO_PENDING_UPDATE` status.

The earlier 20-question answer-quality baseline remains a historical run with
its original source fingerprint. This conversion was checked for SQL execution,
output equivalence, and successful index synchronization; it did not rerun the
20-question AI judges. Future evaluations fingerprint the SQL pipeline source.


## Current benchmark inputs

The current 20-question set uses standalone questions and follow-up histories
without source-publication titles or filenames. Products and customer names
identify the subject matter; reference document/page information is confined to
the scoring expectations. The question IDs, categories, answerability labels,
source revision, and evidence entries are preserved. Reference wording for open
business-use and synthesis questions accepts substantive source-supported answers
without requiring publication attribution.

Benchmark SHA-256: `c4c9644551f4027071bd975e940e04a6f0527434e59dacff49bc7d8a99f5b591`.

The evaluation integrity checks verify both the absence of document-routing cues
in the current inputs and the separation of reference data from agent inputs.
The native evaluation above measures this revised question set. Earlier scores
are retained as historical evidence and use different questions and judges.
