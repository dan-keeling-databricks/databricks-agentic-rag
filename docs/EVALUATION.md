# Check whether answers are useful

The evaluation job asks the agent a repeatable set of questions and uses another
AI model to judge the answers. MLflow keeps the results together so you can
compare changes, read judge explanations, and inspect how the agent searched.

## What is in the question set?

[`evaluation/benchmark.jsonl`](../evaluation/benchmark.jsonl) contains 20 questions:

| Kind | Count | What it checks |
| --- | ---: | --- |
| Factual lookup | 13 | Find and explain facts in a PDF |
| Combine documents | 3 | Bring together evidence from two PDFs |
| Follow-up question | 2 | Understand a question using the supplied chat history |
| Not answerable | 2 | Admit that the documents do not contain the requested information |

The answers were written from three PDFs in the sample collection: the compact
LLM guide, the ingestion ebook, and the digital twin ebook. The source dataset
revision is recorded in every question. Page numbers count from the first PDF
page, including its cover. Each answerable question includes a reference answer,
required facts, and evidence pages. The follow-up tests supply fixed chat history;
they test context handling rather than accumulating errors across a whole chat.

These are **author-derived reference answers awaiting customer review**. They are
not customer-approved ground truth. The PDFs describe products at their original
publication dates; the benchmark tests faithful reading of those documents, not
current product documentation.

The full question set, including reference facts and evidence lists, is saved
unchanged as a run artifact. For compatibility with the initially tested
workspace, only simple values (the reference-answer text, answerable flag, review
status, and source revision) are also written as MLflow expectation annotations.
Custom scorers use the question ID to look up the complete reference record in
memory, so facts and evidence remain part of every check. This avoids an observed
UC trace-readback issue where list-valued expectations were returned as empty
serialized JSON. It does not change the question set, weaken the scoring, or
require a library patch or a second experiment.

## What gets measured?

| Check | How it works | How to read it |
| --- | --- | --- |
| Correctness | AI judge compares the answer with the reference facts | Did the answer respond accurately, or abstain when required? |
| Groundedness | AI judge compares claims and citations with retrieved passages | Does the evidence support what the answer says? |
| Retrieval quality | AI judge reads the passages against the question and required facts | Did search find enough useful material? |
| Citation validity | Code checks document, chunk, and page references against retrieved results | Do the references point to pages that were actually retrieved? |
| Evidence page recall | Code counts how many reference document/pages were retrieved | A diagnostic fraction; other pages may also be valid evidence |
| Response latency | Code measures elapsed time in the agent | How long did the answer take, excluding later judging? |

The two retrieval measures are not applicable to unanswerable questions, so those
rows have no retrieval score. They are excluded from the corresponding averages.
Judge failures and missing assessments are reported as errors, never silently
converted to passing answers. The job fails if predictions or assessments are
missing, while preserving the partial report for diagnosis.

## Run it

First complete the [deployment quickstart](QUICKSTART.md), including ingesting
documents and waiting for the search index to finish updating. Then run the
bundle's evaluation job as shown in that guide. The job imports and calls the
same `RagAgent` class as the app; it does not evaluate a separate imitation.

For local use, install the repository requirements, authenticate with the intended
Databricks profile, and supply the app's configuration variables. Do not copy
tokens into source files. For example, after configuring the selected profile and
`AGENT_ENDPOINT`, `JUDGE_ENDPOINT`, `VECTOR_SEARCH_INDEX`, and
`MLFLOW_EXPERIMENT_ID`, plus `MLFLOW_TRACING_SQL_WAREHOUSE_ID` for the trace
warehouse:

```bash
export DATABRICKS_CONFIG_PROFILE="your-profile"
python -m evaluation.runner --run-name initial-baseline
```

Use a different open-weight judge model from the agent where practical, to reduce
shared blind spots. `JUDGE_ENDPOINT` selects that model. The judge uses the same
authenticated model-client factory as the agent, including Unity AI Gateway when
enabled. Three AI checks run for each answerable question and two for each
unanswerable question; plan for those additional model calls. Evaluation defaults
to two parallel workers. Increase `MLFLOW_GENAI_EVAL_MAX_WORKERS` only after
checking the model route's limits.

To check the deployed job's wiring with one question before running the full set:

```bash
databricks bundle run evaluate_agent -t demo --profile YOUR_PROFILE --params question_limit=1
```

Then run the default full benchmark:

```bash
databricks bundle run evaluate_agent -t demo --profile YOUR_PROFILE
```

The job parameter `question_limit` defaults to `0`, meaning all 20 questions.
Positive values evaluate only the first N questions; negative values are rejected.
For a local smoke test, use `python -m evaluation.runner --limit 2`.
Limited runs are labelled smoke tests in MLflow and are not full benchmark results.

## Read and compare results

Open the MLflow run printed by the job. The run records the benchmark hash, source
revision, agent and judge model routes, search limit, and retrieval count. Each
question has the produced answer, source references, scores, and judge rationales.
Agent traces expose searches and model interactions.

Every run also records `implementation_sha256`: a fingerprint of the relative
paths and exact file contents for the agent, retrieval, configuration, and PDF
pipeline code. This identifies the evaluated implementation even when a job runs
uploaded source files without Git history. Context-size and chat-history limits,
and whether Unity AI Gateway was used, are recorded as run parameters too.

A gateway service name is an alias: its backing model can change while its name
stays the same. The job therefore tries to read the agent and judge services'
configured model destinations before evaluation and saves that routing snapshot.
It does not fetch credentials. If the SDK or permissions prevent this lookup,
the artifact explicitly says `unavailable`; the evaluation can still run, but the
model identity record is incomplete. A routing snapshot records configuration at
that time, not a guarantee that the service will never change during a run.

The job also writes and logs these files as MLflow artifacts under
`evaluation_report/`:

- `BASELINE.md`: a short readable summary with aggregate results and failures.
- `summary.json`: run link, completion counts, benchmark hash, and aggregate metrics.
- `results.json`: each question, reference answer, agent output, and assessment.
- `implementation.json`: the implementation fingerprint and individual source-file hashes.
- `model_services.json`: the configured agent/judge model destinations, or an explicit lookup-unavailable status.

By default these files are also written to `reports/evaluation/` in the execution
environment. Use `--output-dir /Volumes/<catalog>/<schema>/<volume>/evaluations/<run>`
if you want an additional durable copy from a job. MLflow artifacts remain the
standard handover location even when a job's local filesystem is temporary.

Before handover, inspect failures and fix clear implementation defects. Describe
remaining limitations honestly. No numerical quality score blocks this reference
implementation's first deployment. Successful end-to-end execution is required.

When comparing runs, keep the question set and judge model fixed, change one
component at a time, and inspect individual regressions as well as averages. An
improvement on twenty questions is evidence worth investigating; it is not proof
that all customer questions will improve.

## Add customer questions and acceptance thresholds

Copy the existing JSONL structure. Give each question a unique ID. Use the
`inputs.query` field for the question and `inputs.history` for any prior turns.
Write a reviewed `expectations.expected_response`, a list of `expected_facts`,
and the supporting `evidence` filename/page/quote entries. Set `answerable` to
false for a question that should produce an insufficient-evidence response.
Update `review_status` when the customer has approved the answer.

To add an optional minimum score after establishing a baseline, use an exact
aggregate metric name from `summary.json`:

```bash
python -m evaluation.runner --minimum-score "correctness/mean=0.85"
```

This makes the job fail if that metric is missing or below the configured minimum.
Choose the threshold with the customer; 0.85 above is an illustration, not a
promised result. Review AI judge decisions against human assessments before using
them as a release gate.

## Data handling and hardening

Traces and reports contain questions, answers, and document excerpts. Grant access
to the MLflow experiment accordingly. This sample uses public PDFs; customer
deployments should define retention, redaction, and access policies before using
private documents. For production, expand and review the question set, test
permissions and malicious document instructions, establish latency targets under
load, and monitor regressions over time.
