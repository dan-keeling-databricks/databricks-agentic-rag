# Measured benchmark

The native MLflow evaluation completed **20 of 20 questions**, with **17 answers
judged correct (85%)**. All **116 applicable assessments** were saved and read
back successfully, with no missing assessments or scorer errors.

[Open the evaluation run in MLflow](https://adb-7405617409436848.8.azuredatabricks.net/ml/experiments/175182949588215/evaluation-runs/e453f577c3ba4d29a972cd3ac767f688/details).
Use that run to inspect every question, answer, reference, judge explanation and
agent trace. This page is a handover snapshot; MLflow holds the working results.

Measured on 23 November 2026 against 29 PDFs and 448 searchable passages.
Questions and follow-up histories contained no source-document titles or
filenames. Reference answers are **author-derived and await customer review**.

## Results

| Measure | Result |
| --- | ---: |
| Correctness | 85% (17/20) |
| Groundedness | 100% (20/20) |
| Useful retrieval | 94.4% (17/18 answerable questions) |
| Valid citations | 90% (18/20) |
| Reference page recall | 94.4% average over 18 answerable questions |
| Average agent response time | 11.34 seconds |
| Median agent response time | 9.58 seconds |
| 90th-percentile response time | 15.77 seconds |
| Slowest agent response | 23.34 seconds |

Agent response times exclude subsequent judging. The two unanswerable questions
have no retrieval-quality or page-recall scores; they are excluded from those
averages. There were 58 AI-judge and 58 code assessments.

Groundedness asks whether an answer's claims are supported. An answer that
acknowledges insufficient evidence can pass groundedness while failing
correctness if the question should have been answerable.

## Results to inspect

- **q11 — diagram labels.** The assistant could not find the three digital-twin
  maturity stages in the searchable text and abstained, even though the reference
  page was retrieved. Correctness, useful
  retrieval and citation validity failed. This is a reminder that finding
  documents does not ensure every diagram label is available to the agent.
- **q14 — synthesis.** The assistant abstained from combining the documents'
  explanations of a strong data foundation. Correctness and citation validity
  failed; the retrieved passages were judged useful.
- **q13 — judge agreement.** Correctness failed despite a cited answer covering
  ineffective data management, silos and legacy warehouse architecture. The
  judge's explanation focused on the first part of that answer. Review this
  potentially strict decision with a subject-matter expert. The selected
  reference page was not retrieved, so page recall also scored zero; that alone
  does not disqualify evidence from other useful pages.

These original decisions are retained in MLflow. They have not been edited to
improve the reported scores.

## Reproduce this run

- Managed dataset: `classic_stable_dankeeling.agentic_rag.evaluation_questions`,
  **version 1**, digest `6e325a7c0eb675802402aa624bc1f110`.
- All six active registered scorers: **version 1**. The retrieval-quality
  wrapper pins its auxiliary native judge to version 1 as well.
- Answer model: `system.ai.gpt-oss-120b`; judge:
  `system.ai.llama_v3_3_70b_instruct`, through Unity Gateway services.
- Execution: the bundle's serverless notebook job, calling the same `RagAgent`
  as the app. No mocked answers, retrieval results or judgments were used.
- Source PDFs: revision `1a8743c8fe783b3ac42ab37aa18118387fb3c996`.
- Portable seed SHA-256:
  `c4c9644551f4027071bd975e940e04a6f0527434e59dacff49bc7d8a99f5b591`.

Use the dataset and scorer version parameters described in the
[evaluation guide](EVALUATION.md). Also keep the model routes and source corpus
fixed: a gateway service can be changed to point to another model.

## Limits

Twenty questions drawn from three PDFs do not establish quality across a
customer's full collection. No 1,000-PDF load test or concurrent-user test was
performed. Review AI decisions against expert feedback and expand the dataset
before setting acceptance thresholds.

The [historical benchmark](HISTORICAL_BASELINE.md) used source-title cues and
different judge definitions. Its percentages and timings should not be compared
directly with this run as evidence of an improvement.
