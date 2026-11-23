# What to add before production

This reference implementation shows the complete flow with a small amount of
code. Production hardening means adding the controls needed to keep a real
service reliable, secure, affordable, and useful over time. The customer should
choose these controls based on their documents and the decisions the assistant
will support.

## Access and document privacy

The example intentionally uses one shared collection for all authorized app
users. If users should see different documents, enforce those rules at retrieval
time using a trustworthy identity and document permissions. Hiding a source link
in the interface is not access control. Test that unauthorized passages cannot
reach the model, an answer, or a trace.

Give deployment, ingestion, evaluation, and app identities only the permissions
they need. Use separate production identities rather than relying on the
developer's account. Review who can open the app, read the PDF volume and saved
tables, query the index and model routes, and view the MLflow experiment. The app
runs its backend operations under its service identity; shared-corpus access
does not automatically reproduce each signed-in user's source-data permissions.

Treat PDFs as untrusted input. Keep retrieved passages separate from instructions
to the assistant. Add tests for documents that contain misleading instructions,
unexpected content, conflicting evidence, or attempts to disclose unrelated
information. Restrict any future tools to their intended scope.

Traces can contain questions, document excerpts, model inputs, and answers.
The **Agent activity** tab deliberately exposes this shared historical record to
all authorized app users. Before introducing sensitive data, decide whether
activity should be restricted to operators, filtered to a user's own authorized
runs, or redacted. Enforce that policy in the backend trace queries and service
permissions as well as the interface. The app's current shared trace access is
separate from the temporary chat session history.
Define retention, access, deletion, and redaction rules before loading sensitive
content. Review regional data-processing requirements and the terms of the
models and built-in AI functions you use.

## Document updates and deletion

The example's normal ingestion path handles new files with new names. For a
changing corpus, define a stable business document ID and a revision policy.
Decide which revision is searchable, how to show its effective date, and how to
handle duplicate uploads.

Add a deletion flow that removes retired or restricted content from every place
it can remain: source storage, saved parsing/extraction tables, search chunks,
the index, caches, and any retained traces or benchmark artifacts. Check index
synchronization before considering a deletion complete.

Define a retry policy for per-document AI failures. A production system should
retry selected documents rather than require a full refresh of the corpus. Keep
an auditable error queue and alert an owner when documents remain unsearchable.

## Reliability and freshness

Set service expectations: how long new documents may take to become searchable,
how quickly questions should return, and what happens during an outage. Add
monitoring and alerts for failed jobs, stalled index updates, processing errors,
model throttling, missing traces, and unusual response times.

Make retries safe and bounded. Separate temporary service errors from permanent
file problems. Test job restarts, duplicate source delivery, corrupted PDFs,
files near size/page limits, and partial service outages. Tell users when results
may be incomplete or stale.

For larger or frequently changing collections, benchmark file discovery and AI
throughput, consider managed file events where supported, tune batch sizes, and
choose an index capacity/endpoint type based on measured document and passage
counts. Validate recovery and backups. The 29-file demonstration does not prove
performance for 1,000 customer PDFs, concurrent users, or large scanned manuals.

## Answer quality and evaluation

Have subject-matter experts review the reference questions, expected answers,
source pages, and ambiguous cases. Include important real customer questions,
long or scanned PDFs, tables, conflicting versions, multi-document answers,
follow-ups, and questions the corpus cannot answer.

AI judges help compare changes but can be inconsistent or biased. Check a sample
of their decisions against human reviews, preserve judge model/prompt versions,
and consider a different judge model from the answering model. Use deterministic
checks for citation references and timing alongside semantic judgments. A valid
page number alone does not prove that the page supports the answer.

Use MLflow Reviews or labeling workflows to collect expert feedback and resolve
disagreements with AI judges. Consider judge alignment, including MemAlign where
appropriate, after collecting representative human assessments. Manage reference
questions in the linked MLflow dataset and register reviewed scorer versions;
do not let routine evaluation runs overwrite managed edits.

The reference does not enable automatic production monitoring. Its correctness
and retrieval checks require reference answers, facts and evidence pages that
are usually absent from live chat. Design separate checks suitable for live
traffic, sampling and human review before starting a monitoring schedule.

Set quality and latency thresholds appropriate to the intended use, then make
regression checks part of releases. Keep a reviewed evaluation set separate from
questions used to tune prompts. Record model versions, prompts, chunking settings,
corpus revision, index configuration, and code revision so comparisons have
meaning. Re-evaluate after changing AI functions or model routes as well as code.

For important decisions, define when a user must verify sources or seek expert
review. Test insufficient-evidence responses rather than rewarding fluent guesses.

## Deployment and change management

Use separate development, test, and production targets, resource names, identities,
and datasets. Put validation and deployment in CI/CD with scoped credentials,
reviewed changes, pinned dependencies, and a rollback procedure. Keep customer
documents and credentials out of Git.

Track preview/beta dependencies explicitly. `ai_prep_search` support can depend on
workspace enablement and runtime/channel; validate upgrades in a test deployment.
Do not silently swap in different processing behavior when a feature is missing.
Pin schema versions where possible and review saved output contracts before
upgrading them.

Use a private repository until the source, example documents' distribution terms,
and deployment details have been reviewed for sharing. Separate customer-neutral
configuration examples from the values for any particular deployment.

## Costs and capacity

Establish a budget and monitor AI-function processing, model tokens, index
capacity, app compute, jobs, and evaluation runs. A full refresh reruns document AI
operations, so it can cost substantially more than an ordinary incremental update.
Measure cost using representative PDFs; file count alone says little about the
number of pages, passages, or model tokens.

Keep search loops, retrieved context, answer length, and user concurrency bounded.
Use gateway rate limits and usage monitoring when available. Load-test realistic
concurrency and consider queues or admission limits before widening access.
Document how to stop unused apps, jobs, endpoints, and test deployments.

## Conversation history and operations

Chat history currently lives only in the active session. If persistent history
is required, add a suitable store with per-user authorization, retention and
deletion, session isolation, and protection against accidentally mixing users'
conversations. Do not reuse a shared in-memory conversation across users.

Assign owners for corpus changes, failed-document review, benchmark maintenance,
access requests, incident handling, and model/runtime upgrades. Write recovery
steps that another operator can follow, then exercise them before launch.
