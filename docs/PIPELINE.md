# How PDFs become searchable

The pipeline turns each PDF into smaller passages that the assistant can search.
It also keeps the original file details so an answer can point back to its source.

## The five saved stages

1. **`bronze_documents` — remember incoming PDFs.** Auto Loader watches the
   configured volume folder and records new files. It saves the PDF bytes,
   filename, source path, content hash, size, and ingestion time. Lakeflow manages
   the progress checkpoint; a second normal update does not ingest the same file
   again.
2. **`parsed_documents` — read the pages.** `ai_parse_document` reads the PDF's
   text, tables, and layout. The original structured result is saved, including
   any parsing errors. Empty files and files above 100 MB stay in the first
   stage and are shown as failures in the status table.
3. **`prepared_documents` — prepare search and extract metadata.**
   `ai_prep_search` divides the parsed document into meaningful passages and adds
   context useful for search. Separately, `ai_extract` extracts a title, short
   summary, and topics. These two raw results are saved before use downstream.
4. **`document_chunks` — publish searchable passages.** Each row has the passage
   text, text to embed, extracted metadata, and source/page details. A stable hash
   combines document identity and passage position to create its unique key.
   Change Data Feed is enabled so the AI Search index can pick up new rows.
5. **`document_processing_status` — make failures visible.** This small
   materialized view combines saved stage results. It shows whether each document
   is ready, failed parsing/search preparation, produced no passages, or has a
   metadata extraction problem. It does not call the AI functions again.

Each AI operation is saved once per document during a normal incremental update.
A deliberate full refresh processes the PDFs again and incurs new AI-function
charges. The status view can refresh without repeating those AI operations.

## Configuration

The bundle supplies these pipeline settings:

| Setting | Purpose |
| --- | --- |
| `rag.source_volume` | Full `/Volumes/<catalog>/<schema>/<volume>[/folder]` path holding the PDFs. |
| `rag.extraction_schema` | JSON schema for `ai_extract`. Defaults to `title` (string), `summary` (string), and `topics` (array of strings). |

Table names are relative to the pipeline's configured catalog and schema. There
is no workspace address or customer-specific catalog name in the pipeline code.
If you change extraction fields, update downstream projections and app metadata
handling as needed; the raw extraction result is preserved for inspection.

## Search table contract

`document_chunks` exposes:

| Column | Meaning |
| --- | --- |
| `chunk_id` | Unique, stable passage key used as the search index primary key. |
| `document_id` | Hash of source path and PDF content hash. |
| `chunk_position` | Zero-based passage position within a document. |
| `chunk_to_embed` | Context-enriched text used to generate embeddings. |
| `chunk_to_retrieve` | Source passage returned to the agent. |
| `source_path`, `filename` | Original PDF location and name. |
| `page_start`, `page_end` | One-based physical PDF page range; may be null if the AI result omits page provenance. |
| `page_count` | Number of pages reported by the parser. |
| `title`, `summary`, `topics` | Extracted document metadata. |
| `content_sha256`, `file_size_bytes`, `file_modified_at`, `ingested_at` | Deterministic file and ingestion details. |
| `extraction_error` | Metadata extraction error, if any. |

The page fields come from each `ai_prep_search` chunk's `pages[].page_id` field,
which is zero-based. The pipeline adds one for human-readable physical PDF page
numbers. These can differ from printed page labels in the document. It never
asks a model to invent a page number. If provenance is missing, the assistant
must disclose that it is unavailable rather than manufacture a citation.

Only nonempty, valid passages enter the index. A metadata error does not discard
otherwise searchable content: the filename supplies a fallback title, and the
status view flags the extraction problem.

## Sample documents

`scripts/load_sample_documents.py` downloads the 29 public PDFs from the agreed
[dbdemos corpus](https://github.com/databricks-demos/dbdemos-dataset/tree/1a8743c8fe783b3ac42ab37aa18118387fb3c996/llm/databricks-pdf-documentation).
The revision is pinned to `1a8743c8fe783b3ac42ab37aa18118387fb3c996` so a later
upstream change does not silently alter the benchmark. It verifies Git blob
hashes and writes a `sample_manifest.json` with SHA-256 hashes, source URLs,
file sizes, and the revision. The upstream `NOTICE` is preserved alongside it.
PDFs themselves are not committed to this repository.

Download only, without Databricks access:

```bash
python scripts/load_sample_documents.py --output-dir /tmp/rag-sample
```

Upload to an existing volume from your computer, using a profile you select:

```bash
python scripts/load_sample_documents.py \
  --volume /Volumes/YOUR_CATALOG/YOUR_SCHEMA/YOUR_VOLUME \
  --profile YOUR_PROFILE
```

In a Databricks job, pass `--use-mounted-volume` to use the mounted volume and the
job's identity without a local profile. Repeating the loader skips identical files and
refuses to overwrite files with different content. New customer PDFs should use
new filenames. The pipeline ignores `NOTICE` and JSON manifests because they
are not PDFs.

## Failures and reprocessing

Inspect `document_processing_status` after every update. A document with a
page-level parser error is retained in `parsed_documents` and is not indexed;
the reference implementation avoids silently presenting a partial document as
complete. If an AI service call fails the pipeline itself, inspect the pipeline
update's error details, correct the cause, and rerun the update.

For the small reference corpus, a **full refresh** is the simplest documented
way to retry saved per-document AI errors after fixing their cause. It rereads
the whole source and reruns AI operations, so review the processing cost first.
Then synchronize the search index again. Full refresh is an explicit maintenance
action; it is not part of the normal ingestion job. Selective retry queues,
document replacement, deletion propagation, and revision management belong in
the customer's operational hardening work.

## Prerequisites and limits

- `ai_prep_search` is a beta feature and requires Databricks Runtime 18.2 or
  newer, or a compatible serverless environment. Serverless environment version
  3 or later is required for VARIANT support; feature availability must also be
  checked in the target workspace and pipeline channel.
- `ai_parse_document` requires Runtime 17.3 or newer and region availability.
  Its documented limits are 500 pages and 100 MB per document. The pipeline
  screens file sizes at 100,000,000 bytes. Page-count and content failures still
  need review in the saved parser errors.
- The parser/preparation output schema is pinned to version `2.0`. Metadata
  extraction also uses version `2.0`. These built-in AI functions select their
  own platform-managed models; the configurable chat/judge models do not change
  those internal models.
- The customer sizing assumption is 1,000 PDFs. The actual supplied sample has
  29 PDFs; successful sample processing is not a 1,000-PDF performance test.

Official references: [AI document parsing](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_parse_document),
[AI search preparation](https://docs.databricks.com/aws/en/sql/language-manual/functions/ai_prep_search),
[Auto Loader options](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/options).
