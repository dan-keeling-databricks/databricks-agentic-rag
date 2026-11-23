-- Incremental PDF preparation for AI Search.
-- Run in Lakeflow Spark Declarative Pipelines. Each AI result is saved before
-- another stage reads it. Pipeline parameters supply the volume and JSON schema.

CREATE OR REFRESH STREAMING TABLE bronze_documents
COMMENT 'Original PDFs and deterministic source metadata; Auto Loader tracks new files.'
AS
WITH files AS (
  SELECT path, content, length, modificationTime,
         sha2(content, 256) AS content_sha256
  FROM STREAM read_files(
    :source_volume,
    format => 'binaryFile',
    recursiveFileLookup => true
  )
  WHERE lower(path) LIKE '%.pdf'
)
SELECT
  sha2(concat_ws(chr(10), path, content_sha256), 256) AS document_id,
  path AS source_path,
  regexp_extract(path, '([^/]+)$', 1) AS filename,
  content_sha256,
  length AS file_size_bytes,
  modificationTime AS file_modified_at,
  current_timestamp() AS ingested_at,
  content
FROM files;

CREATE OR REFRESH STREAMING TABLE parsed_documents
COMMENT 'Persisted ai_parse_document results, including per-page parsing errors.'
AS
SELECT
  document_id, source_path, filename, content_sha256,
  file_size_bytes, file_modified_at, ingested_at,
  ai_parse_document(content, map('version', '2.0')) AS parsed
FROM STREAM(bronze_documents)
-- Oversized and empty PDFs stay in bronze and appear in the status view.
WHERE file_size_bytes > 0 AND file_size_bytes <= 100000000;

CREATE OR REFRESH STREAMING TABLE prepared_documents
COMMENT 'Persisted search preparation and configurable ai_extract metadata results.'
AS
WITH parsed_status AS (
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
  size(variant_get(parsed, '$.document.pages', 'ARRAY<VARIANT>')) AS page_count,
  ai_prep_search(parsed, map('version', '2.0')) AS prepared,
  ai_extract(parsed, :extraction_schema, map('version', '2.0')) AS extracted
FROM parsed_status
WHERE parsed IS NOT NULL AND parse_error IS NULL;

CREATE OR REFRESH STREAMING TABLE document_chunks
COMMENT 'One search-ready row per chunk. Page numbers are one-based physical PDF pages.'
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
WITH preparation_status AS (
  SELECT *,
    CASE WHEN CAST(prepared:error_status AS STRING) IN ('', 'null', '[]', '{}')
         THEN CAST(NULL AS STRING)
         ELSE CAST(prepared:error_status AS STRING)
    END AS prep_error
  FROM STREAM(prepared_documents)
), passages AS (
  SELECT *,
    explode(variant_get(prepared, '$.document.contents', 'ARRAY<VARIANT>')) AS chunk
  FROM preparation_status
  WHERE prepared IS NOT NULL AND prep_error IS NULL
), decoded AS (
  SELECT *,
    variant_get(chunk, '$.chunk_position', 'INT') AS chunk_position,
    variant_get(chunk, '$.chunk_to_retrieve', 'STRING') AS chunk_to_retrieve,
    variant_get(chunk, '$.chunk_to_embed', 'STRING') AS chunk_to_embed,
    transform(
      variant_get(chunk, '$.pages', 'ARRAY<STRUCT<page_id:INT,image_uri:STRING>>'),
      page -> page.page_id + 1
    ) AS page_numbers
  FROM passages
)
SELECT
  -- Match the original identity bytes exactly; chr(10) is a newline.
  sha2(concat_ws(chr(10), document_id, CAST(chunk_position AS STRING)), 256) AS chunk_id,
  document_id, source_path, filename, content_sha256,
  file_size_bytes, file_modified_at, ingested_at,
  chunk_position, chunk_to_retrieve, chunk_to_embed, page_count,
  array_min(page_numbers) AS page_start,
  array_max(page_numbers) AS page_end,
  coalesce(try_variant_get(extracted, '$.response.title', 'STRING'), filename) AS title,
  try_variant_get(extracted, '$.response.summary', 'STRING') AS summary,
  try_variant_get(extracted, '$.response.topics', 'ARRAY<STRING>') AS topics,
  CASE WHEN CAST(extracted:error_message AS STRING) IN ('', 'null', '[]', '{}')
       THEN CAST(NULL AS STRING)
       ELSE CAST(extracted:error_message AS STRING)
  END AS extraction_error
FROM decoded
WHERE chunk_position IS NOT NULL
  AND length(trim(chunk_to_retrieve)) > 0
  AND length(trim(chunk_to_embed)) > 0;

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
