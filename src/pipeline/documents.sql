-- Turn PDFs into searchable passages with document and page references.
--
-- Run this file in Lakeflow Spark Declarative Pipelines (SDP). The bundle sets
-- the destination catalog/schema and binds these parameters in pipeline settings:
--   :source_volume     Unity Catalog volume folder containing the PDFs.
--   :extraction_schema JSON describing the metadata requested from ai_extract
--                      (title, summary, and topics by default).
--
-- Data moves through five saved datasets:
--   bronze_documents -> parsed_documents -> prepared_documents -> document_chunks
--   document_processing_status joins these datasets to report each PDF's status.
--
-- The four streaming tables process new arrivals incrementally. Lakeflow manages
-- their checkpoints, so a normal update skips files already ingested. A full
-- refresh resets that progress and repeats the billed AI processing. The tables
-- save the AI results for downstream reuse.
--
-- 1. INGEST: retain the PDF bytes and record reliable source-file details.

CREATE OR REFRESH STREAMING TABLE bronze_documents
COMMENT 'Original PDFs and deterministic source metadata; Auto Loader tracks new files.'
AS
WITH files AS (
  SELECT path, content, length, modificationTime,
         sha2(content, 256) AS content_sha256
  -- STREAM read_files uses Auto Loader; without STREAM this would be a batch read.
  FROM STREAM read_files(
    :source_volume,
    format => 'binaryFile',
    recursiveFileLookup => true
  )
  -- Ignore companion files such as NOTICE and the sample JSON manifest.
  WHERE lower(path) LIKE '%.pdf'
)
SELECT
  -- A hash is a repeatable identifier. Include both the path and content hash:
  -- identical PDFs at different paths remain distinct source documents.
  -- chr(10) separates the values with a newline, independent of SQL escaping.
  sha2(concat_ws(chr(10), path, content_sha256), 256) AS document_id,
  path AS source_path,
  regexp_extract(path, '([^/]+)$', 1) AS filename,
  content_sha256,
  length AS file_size_bytes,
  modificationTime AS file_modified_at,
  current_timestamp() AS ingested_at,
  content
FROM files;

-- 2. PARSE: read text, tables, and layout from each eligible PDF.
-- Keep the complete returned VARIANT (a structured JSON-like value), including
-- error details, so failures can be inspected without calling the AI again.
-- The version option selects the output format; it does not pin an AI model.
CREATE OR REFRESH STREAMING TABLE parsed_documents
COMMENT 'Persisted ai_parse_document results, including per-page parsing errors.'
AS
SELECT
  document_id, source_path, filename, content_sha256,
  file_size_bytes, file_modified_at, ingested_at,
  ai_parse_document(content, map('version', '2.0')) AS parsed
FROM STREAM(bronze_documents)
-- Avoid AI calls for empty files or files above the decimal 100 MB size limit.
-- These documents stay in bronze and remain visible in the final status view.
-- The parser itself reports page-count, content, and other parsing failures.
WHERE file_size_bytes > 0 AND file_size_bytes <= 100000000;

-- 3. PREPARE: produce search passages and extract metadata from the parsed PDF.
-- A reported parsing error prevents the document from reaching this stage;
-- this avoids indexing a partially parsed document as though it were complete.
CREATE OR REFRESH STREAMING TABLE prepared_documents
COMMENT 'Persisted search preparation and configurable ai_extract metadata results.'
AS
WITH parsed_status AS (
  -- Error fields can be absent, SQL NULL, or an empty JSON/string value.
  -- Normalize the empty representations to SQL NULL, meaning "no reported error".
  -- A genuine error remains intact. An existing SQL NULL stays NULL via ELSE.
  SELECT *,
    CASE WHEN CAST(parsed:error_status AS STRING) IN ('', 'null', '[]', '{}')
         THEN CAST(NULL AS STRING)
         ELSE CAST(parsed:error_status AS STRING)
    END AS parse_error
  FROM STREAM(parsed_documents)
)
SELECT
  document_id, source_path, filename, content_sha256,
  file_size_bytes, file_modified_at, ingested_at,
  -- Count the pages listed in the saved parser output.
  size(variant_get(parsed, '$.document.pages', 'ARRAY<VARIANT>')) AS page_count,
  -- Prepare meaningful passages and extra context for semantic search.
  ai_prep_search(parsed, map('version', '2.0')) AS prepared,
  -- Extract descriptive metadata; file identity and page numbers come from data.
  ai_extract(parsed, :extraction_schema, map('version', '2.0')) AS extracted
FROM parsed_status
WHERE parsed IS NOT NULL AND parse_error IS NULL;

-- 4. PUBLISH: produce one search-index row per usable passage (or "chunk").
-- The AI Search Delta Sync index reads this table. Change Data Feed records its
-- changes so the index can synchronize them after the pipeline update completes.
CREATE OR REFRESH STREAMING TABLE document_chunks
COMMENT 'One search-ready row per chunk. Page numbers are one-based physical PDF pages.'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
WITH preparation_status AS (
  -- Apply the same empty-error normalization to the saved search-preparation result.
  SELECT *,
    CASE WHEN CAST(prepared:error_status AS STRING) IN ('', 'null', '[]', '{}')
         THEN CAST(NULL AS STRING)
         ELSE CAST(prepared:error_status AS STRING)
    END AS prep_error
  FROM STREAM(prepared_documents)
), passages AS (
  -- Convert the contents array to rows. VARIANT must first be read as a typed
  -- array before explode can turn each array element into a separate passage.
  SELECT *,
    explode(variant_get(prepared, '$.document.contents', 'ARRAY<VARIANT>')) AS chunk
  FROM preparation_status
  WHERE prepared IS NOT NULL AND prep_error IS NULL
), decoded AS (
  -- Give fields inside each structured passage concrete SQL types for the index.
  -- Embed the context-enriched text; return the original passage to the agent.
  SELECT *,
    variant_get(chunk, '$.chunk_position', 'INT') AS chunk_position,
    variant_get(chunk, '$.chunk_to_retrieve', 'STRING') AS chunk_to_retrieve,
    variant_get(chunk, '$.chunk_to_embed', 'STRING') AS chunk_to_embed,
    -- Parser page IDs start at zero. Citations count physical PDF pages from
    -- one, including the cover; printed page labels in the PDF may differ.
    transform(
      variant_get(chunk, '$.pages', 'ARRAY<STRUCT<page_id:INT,image_uri:STRING>>'),
      page -> page.page_id + 1
    ) AS page_numbers
  FROM passages
)
SELECT
  -- Combine document ID and passage position to make a repeatable search key.
  -- Passage positions from different documents receive separate identities.
  sha2(concat_ws(chr(10), document_id, CAST(chunk_position AS STRING)), 256) AS chunk_id,
  document_id, source_path, filename, content_sha256,
  file_size_bytes, file_modified_at, ingested_at,
  chunk_position, chunk_to_retrieve, chunk_to_embed, page_count,
  -- Keep the passage's full page range. Missing page provenance stays NULL;
  -- the retrieval layer excludes rows without a valid page range.
  array_min(page_numbers) AS page_start,
  array_max(page_numbers) AS page_end,
  -- Metadata is optional: read it safely and use the filename if title is absent.
  -- Extraction errors are retained below; useful passage text can still be indexed.
  coalesce(try_variant_get(extracted, '$.response.title', 'STRING'), filename) AS title,
  try_variant_get(extracted, '$.response.summary', 'STRING') AS summary,
  try_variant_get(extracted, '$.response.topics', 'ARRAY<STRING>') AS topics,
  CASE WHEN CAST(extracted:error_message AS STRING) IN ('', 'null', '[]', '{}')
       THEN CAST(NULL AS STRING)
       ELSE CAST(extracted:error_message AS STRING)
  END AS extraction_error
FROM decoded
-- Require a usable key position and both text forms before publishing to search.
WHERE chunk_position IS NOT NULL
  AND length(trim(chunk_to_retrieve)) > 0
  AND length(trim(chunk_to_embed)) > 0;

-- 5. REPORT: show one status row for every source PDF, including failed files.
-- This is a materialized view with batch reads of the saved tables: the joins
-- and counts need their current contents, rather than only newly arriving rows.
-- Refreshing this view reads stored AI results and makes no new AI calls.
CREATE OR REFRESH MATERIALIZED VIEW document_processing_status
COMMENT 'One row per source PDF showing readiness, failures, and raw AI error details.'
AS
WITH parsed_status AS (
  SELECT document_id,
    parsed IS NOT NULL AS has_parse_result,
    CASE WHEN CAST(parsed:error_status AS STRING) IN ('', 'null', '[]', '{}')
         THEN CAST(NULL AS STRING)
         ELSE CAST(parsed:error_status AS STRING)
    END AS parse_error
  FROM parsed_documents
), preparation_status AS (
  SELECT document_id, page_count,
    prepared IS NOT NULL AS has_prep_result,
    CASE WHEN CAST(prepared:error_status AS STRING) IN ('', 'null', '[]', '{}')
         THEN CAST(NULL AS STRING)
         ELSE CAST(prepared:error_status AS STRING)
    END AS prep_error,
    CASE WHEN CAST(extracted:error_message AS STRING) IN ('', 'null', '[]', '{}')
         THEN CAST(NULL AS STRING)
         ELSE CAST(extracted:error_message AS STRING)
    END AS extraction_error,
    extracted IS NOT NULL AS has_extraction_result
  FROM prepared_documents
), chunk_counts AS (
  SELECT document_id, count(*) AS chunk_count
  FROM document_chunks
  GROUP BY document_id
), status_inputs AS (
  -- Start from bronze and LEFT JOIN later stages so missing/failed processing
  -- does not make a source document disappear from the report.
  SELECT
    b.document_id, b.source_path, b.filename, b.content_sha256,
    b.file_size_bytes, b.file_modified_at, b.ingested_at,
    p.has_parse_result, p.parse_error,
    s.page_count, s.has_prep_result, s.prep_error,
    s.extraction_error, s.has_extraction_result,
    coalesce(c.chunk_count, CAST(0 AS BIGINT)) AS chunk_count
  FROM bronze_documents b
  LEFT JOIN parsed_status p ON b.document_id = p.document_id
  LEFT JOIN preparation_status s ON b.document_id = s.document_id
  LEFT JOIN chunk_counts c ON b.document_id = c.document_id
)
SELECT *,
  -- Report the earliest blocking problem first. For example, an oversized PDF
  -- is classified by size rather than by the parsing result it never received.
  -- Metadata problems are a separate warning once searchable passages exist.
  CASE
    WHEN file_size_bytes <= 0 THEN 'empty_file'
    WHEN file_size_bytes > 100000000 THEN 'file_too_large'
    WHEN NOT coalesce(has_parse_result, false) THEN 'parse_missing'
    WHEN parse_error IS NOT NULL THEN 'parse_error'
    WHEN NOT coalesce(has_prep_result, false) THEN 'prep_missing'
    WHEN prep_error IS NOT NULL THEN 'prep_error'
    WHEN chunk_count = 0 THEN 'no_searchable_chunks'
    WHEN extraction_error IS NOT NULL OR NOT coalesce(has_extraction_result, false)
      THEN 'ready_with_metadata_error'
    ELSE 'ready'
  END AS status
FROM status_inputs;
