# Check whether answers are useful

Evaluation means asking a repeatable set of questions, comparing the answers
with reviewed references, and inspecting where the agent succeeded or struggled.
An AI judge helps assess answer quality; code checks references and timing.

**MLflow is the place to manage the questions, scoring rules and results.** The
experiment's **Datasets**, **Scorers** and evaluation runs are the source of truth.
The repository provides a starter question set and two readable Databricks
notebooks to set up and run this workflow.

## Set it up once

After [deploying and loading the PDFs](QUICKSTART.md), run:

```bash
databricks bundle run setup_evaluation -t demo --profile YOUR_PROFILE
```

The setup job runs [`notebooks/setup_evaluation.py`](../notebooks/setup_evaluation.py).
It creates or seeds the managed Unity Catalog dataset
`<catalog>.<schema>.evaluation_questions`, links it to the existing MLflow
experiment, and registers versioned scoring definitions.

This is an explicit setup action. **An ordinary benchmark run does not copy the
starter questions over your managed edits or register new scorer versions.**
Rerunning setup leaves an existing dataset unchanged and publishes scorer
versions. Update managed records through MLflow's dataset tools or an explicit
`merge_records()` operation; review those changes before evaluating them.

Open the experiment linked from the app's Architecture tab. In **Datasets**, open
`evaluation_questions` to inspect and maintain the questions and reference
answers. In **Scorers**, inspect the registered definitions and their versions.
You can now work with these managed assets rather than editing a local report.

## What is in the starter question set?

[`evaluation/benchmark.jsonl`](../evaluation/benchmark.jsonl) is a portable seed,
not the live question store. It contains 20 questions:

| Kind | Count | What it checks |
| --- | ---: | --- |
| Factual lookup | 13 | Find and explain facts in a PDF |
| Combine documents | 3 | Bring together evidence from two PDFs |
| Follow-up question | 2 | Understand a question using supplied chat history |
| Not answerable | 2 | Admit that the documents do not contain the requested information |

Reference answers were written from three sample PDFs: the compact LLM guide,
the ingestion ebook and the digital twin ebook. Evidence includes document names,
physical PDF page numbers and supporting quotes. Each record identifies the
source revision and its review status.

The questions and fixed follow-up histories do not name source documents,
filenames, chapters or evidence pages. Product and organization names remain
where they identify the subject. The agent receives only the question and chat
history; the answer and evidence annotations are reserved for scoring.

These are **author-derived reference answers awaiting customer review**, not
customer-approved truth. The benchmark checks faithful reading of those PDFs,
not whether their historical product descriptions are still current. The
[historical baseline](HISTORICAL_BASELINE.md) used an earlier question set with source-title
cues; its scores do not measure the current questions or this managed workflow.

### How reference facts and pages are stored

The managed dataset retains the full references. `expected_response` holds the
reference answer. Lists of required facts and source evidence are stored as JSON
text in `expected_facts_json` and `evidence_json`; the scorers decode them when
checking a result. This avoids an observed Unity Catalog trace-readback issue
with nested list-valued expectations. No external lookup map or separate report
is needed to recover the scoring references.

When editing those fields, keep valid JSON. For a new customer question, provide
its question and optional history, expected answer, required facts, evidence,
answerable flag and review status. Use unanswerable cases to test whether the
assistant can acknowledge missing evidence. Review edits with a subject-matter
expert before treating the answers as approved.

## Run an evaluation

Run the bundle's notebook job:

```bash
databricks bundle run evaluate_agent -t demo --profile YOUR_PROFILE
```

[`notebooks/evaluate_agent.py`](../notebooks/evaluate_agent.py) retrieves the managed
dataset and registered scorer versions, calls the same `RagAgent` used by the
app, and passes its results to **`mlflow.genai.evaluate()`**. The native MLflow
run contains the predictions, assessments, judge explanations and agent traces.
It does not depend on a standalone local runner or generated report files.

You can also open the deployed notebook from the job task to read or adapt the
code. MLflow's **Run evaluation → Use code** route is appropriate for this
workflow because its scorers include custom functions. Use the notebook rather
than assuming every custom scorer can be launched directly by a generic UI form.
**Select traces** can be used to rescore already recorded traces when the needed
reference expectations are present; that scores existing answers instead of
asking the agent to produce new ones.

Use a different judge model from the answer model where practical. Both use the
configured Unity Gateway services. Judging adds model calls and inference charges
in addition to the agent's own work.

## What gets measured?

| Check | How it works | How to read it |
| --- | --- | --- |
| Correctness (`correctness`) | AI judge compares the answer with the reference answer and facts | Did it answer accurately, or abstain when required? |
| Groundedness (`groundedness`) | AI judge compares claims with retrieved passages | Does the evidence support the answer? |
| Retrieval quality (`retrieval_quality`) | AI judge checks whether the passages contain useful evidence | Did search find enough material? |
| Citation validity (`valid_citations`) | Code checks document, chunk and page references against retrieval | Were the cited pages actually retrieved? |
| Evidence page recall (`evidence_recall`) | Code compares retrieved pages with annotated evidence pages | What fraction of the reference pages was found? Other pages may also be useful. |
| Response latency (`latency_seconds`) | Code measures elapsed time in the agent | How long did the answer take, excluding later judging? |

There are seven registered definitions, including the auxiliary
`retrieval_quality_judge`, and six active evaluation metrics. The active retrieval
quality scorer handles not-applicable cases before invoking its AI judge. Both
retrieval measures are not applicable to unanswerable questions; those rows are
excluded from their averages. They should not be read as failed retrieval tests.
Missing assessments and judge errors must be investigated rather than counted as
passing answers.

## Read and compare results

In the experiment, open the evaluation run and inspect both aggregate scores and
individual rows. Read the expected answer, generated answer, assessment rationale,
retrieved passages and trace. A high average can hide an important bad answer.

The evaluation job's `dataset_version` and `scorer_versions` parameters can pin
saved versions. Leaving them blank and `{}` respectively resolves the latest
saved versions once at the start; the run records the versions actually used.
For `scorer_versions`, provide a JSON mapping for all six active scorer names.

Compare runs using the same managed dataset revision and scorer versions. Also
keep the source documents, agent configuration and backing judge model fixed
when testing a change. A Unity Gateway service name is a route: its backing model
can change even when the service name stays the same. Record that change when
interpreting a comparison.

The [measured baseline](BASELINE.md) records the first completed native run:
20 questions, 116 applicable assessments, and 85% correctness. Read subsequent
managed runs in MLflow. Fix clear implementation defects, document remaining
limitations, and agree meaningful
quality and latency thresholds with the customer after reviewing a baseline.
No automatic production-monitoring schedule or numerical release gate is enabled
by this reference.

## Human review and production monitoring

Use MLflow Reviews or labeling workflows to collect expert judgments on useful
examples and disagreements with AI judges. Judge alignment, including MemAlign
where appropriate, is a follow-on hardening task.

The reference scorers rely on known answers and evidence pages. Those references
do not normally exist for arbitrary live chat questions, so registering scorers
here does **not** enable automatic production monitoring. Design a separate
monitoring plan with checks suitable for live traffic, appropriate sampling,
reviewed permissions and clear ownership before enabling it.

Questions, expected answers, model outputs and source passages can contain
sensitive material. Apply access, retention and redaction policies to the managed
dataset, MLflow experiment and trace tables before using private documents.
