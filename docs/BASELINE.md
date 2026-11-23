# What the first benchmark found

The assistant completed **20 of 20 questions** against the deployed PDFs, search
index, and models. The independent AI judge rated **16 of 20 answers correct
(80%)**. This is a measured starting point for improving the example, not a
customer acceptance score.

[Open the full MLflow run](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/runs/b35c5eb751cb423b8904dbd74f1cbc4a)
for answers, source passages, traces, judge explanations, and downloadable reports.
Measured on 23 November 2026. The reference answers were written from three sample
PDFs and **await customer review**.

## Results in plain language

| Measure | Result | Meaning |
| --- | ---: | --- |
| Correctness | 80% (16/20) | The judge found the requested facts, or an appropriate admission of missing evidence. |
| Groundedness | 85% (17/20) | The judge found support for the answer's claims in retrieved passages. See judge limitations below. |
| Valid citations | 90% (18/20) | References matched retrieved documents/pages, or the unanswerable question needed no references. |
| Useful retrieval | 94.4% (17/18) | The judge considered the passages sufficient for an answerable question. |
| Reference page recall | 100% average over 18 answerable questions | Search found the selected reference pages. This does not mean every fact or diagram label survived PDF processing. |
| Average response time | 59.0 seconds | Time spent answering, excluding subsequent judging. |
| Median response time | 50.5 seconds | Half the responses were faster than this. |
| 90th-percentile response time | 83.0 seconds | Approximately nine out of ten responses were within this time in this small run. |
| Slowest response | 84.9 seconds | The longest observed answer time. |

Retrieval measures exclude the two questions that the documents cannot answer.
All applicable scores were captured. Optional quality thresholds were unset
for this benchmark run.

## Answers and judgments that need attention

We reviewed the actual answers and retrieved passages, as well as the scores:

- **q02 — answered the wrong part of a document.** The question asked for four
  drivers of LLM adoption. The answer described model milestones instead, even
  though the requested driver text was retrieved. Supported facts can still fail
  to answer the question.
- **q11 — a diagram lost useful labels.** Search found the reference page, but
  PDF preparation retained a generic diagram description without its three stage
  names. The assistant then declined to answer. This explains why perfect page
  recall did not produce a correct answer.
- **q15 — declined too readily.** After three searches the assistant reported
  insufficient evidence; the judge considered the retrieved material sufficient
  to combine facts from the ingestion and digital-twin documents.
- **q19 — applied another company's number to the customer.** The assistant used
  an Akamai example's 5–7 minute ingestion SLA when asked about “our customer.”
  The source supports that example, but does not establish the customer's
  contractual commitment. The correctness judge failed the answer even though
  the groundedness judge passed it.
- **q20 — the judge made a questionable decision.** The assistant correctly said
  the documents did not establish a fictional company's 2026 software budget.
  Correctness passed, but the groundedness judge penalized the absence of factual
  claims, despite its instructions allowing this response. We retained the
  original score and explanation rather than editing a result to improve it.

A later one-question serverless wiring test also declined an answerable q01
despite useful retrieved passages. It is documented separately in the
[validation record](VALIDATION.md); it is not folded into these 20-question
averages. Repeated model calls can vary even with temperature set to zero.

Useful next experiments are better handling of diagrams, tighter checks that an
answer addresses the requested entity and facts, and human review of judge
agreement. Change one component at a time and rerun the same benchmark before
claiming an improvement.

## What was evaluated

This run predates the SQL pipeline conversion. The [validation record](VALIDATION.md#sql-document-pipeline)
records the SQL execution and output-equivalence checks. These original benchmark
results and their implementation fingerprint are retained unchanged.

- Corpus: all **29 PDFs**, pinned to source revision
  `1a8743c8fe783b3ac42ab37aa18118387fb3c996`, producing **448 search passages**.
- Questions: 20, with reference evidence drawn from the compact LLM guide,
  ingestion ebook, and digital-twin ebook.
- Answer model: `system.ai.gpt-oss-120b`; independent judge:
  `system.ai.llama_v3_3_70b_instruct`, both through Unity AI Gateway services.
- Agent: the same `RagAgent` class and settings used by the app; at most three
  searches, six results per search. The full baseline runner executed locally
  against the real deployed services and Unity Catalog-backed MLflow experiment.
  It used no mocked model, search, or judge responses. The deployed serverless
  job is validated separately in the [validation record](VALIDATION.md).
- Benchmark SHA-256:
  `2518dd1af6a33f47ec737a7641e49ce2dbb43cbb7b4d1b0faa5fc8d8f9874ea7`.
- Evaluated implementation SHA-256:
  `db8286db672bd096797894ac6348c024c0d6e0acd3db29705901a1e724b38413`.

The MLflow run's `evaluation_report/` artifacts include the detailed results,
metric summary, implementation file hashes, and model-routing snapshot. The exact
benchmark is saved under `benchmark/`.

Two unanswerable questions initially encountered a logging compatibility issue:
MLflow rejected empty retrieval scores and dropped their assessment batches.
The eight applicable assessments were restored from the already captured real
scores and explanations, then read back to verify them. No answer, judge result,
or aggregate metric was changed. The scorer now skips inapplicable MLflow
annotations while keeping their explanations in the report. A repair note is
included with the run artifacts.

## Limits

Twenty questions are too few to predict quality across a customer's document
collection. No 1,000-PDF load test or concurrent-user test was performed. AI
judgments are fallible, page recall is only a diagnostic, and a valid citation
does not prove a claim applies to the right company. Document content reflects
publication dates rather than current Databricks product behavior.

Use the [evaluation guide](EVALUATION.md) to rerun, compare changes, and replace
the sample questions with customer-reviewed examples.
