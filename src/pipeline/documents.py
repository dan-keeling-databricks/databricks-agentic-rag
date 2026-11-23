"""Incremental PDF preparation for AI Search.

Run this file in Lakeflow Spark Declarative Pipelines, not as a local script.
Each expensive AI result is saved before a downstream stage reads it.
"""

import json

from pyspark import pipelines as dp
from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.getOrCreate()
SOURCE_VOLUME = spark.conf.get("rag.source_volume")
EXTRACTION_SCHEMA = spark.conf.get(
    "rag.extraction_schema",
    json.dumps(
        {
            "title": {"type": "string", "description": "The document title."},
            "summary": {
                "type": "string",
                "description": "A brief factual summary of the document in two sentences.",
            },
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Up to five short subject labels supported by the document.",
            },
        }
    ),
)
# Fail early for a malformed configuration, before an expensive update starts.
json.loads(EXTRACTION_SCHEMA)
if not SOURCE_VOLUME.startswith("/Volumes/"):
    raise ValueError("rag.source_volume must be a full /Volumes/catalog/schema/volume path")

MAX_PDF_BYTES = 100_000_000
IDENTITY_COLUMNS = [
    "document_id", "source_path", "filename", "content_sha256",
    "file_size_bytes", "file_modified_at", "ingested_at",
]


def error_text(expression):
    """Normalize absent/empty AI error fields without losing their raw result."""
    value = F.expr(f"CAST({expression} AS STRING)")
    return F.when(
        value.isNull() | value.isin("", "null", "[]", "{}"), F.lit(None).cast("string")
    ).otherwise(value)


@dp.table(comment="Original PDFs and deterministic source metadata; Auto Loader tracks new files.")
def bronze_documents():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "binaryFile")
        .option("recursiveFileLookup", "true")
        .load(SOURCE_VOLUME)
        .where(F.lower(F.col("path")).endswith(".pdf"))
        .withColumn("content_sha256", F.sha2("content", 256))
        .select(
            F.sha2(F.concat_ws("\n", "path", "content_sha256"), 256).alias("document_id"),
            F.col("path").alias("source_path"),
            F.regexp_extract("path", r"([^/]+)$", 1).alias("filename"),
            "content_sha256", F.col("length").alias("file_size_bytes"),
            F.col("modificationTime").alias("file_modified_at"),
            F.current_timestamp().alias("ingested_at"), "content",
        )
    )


@dp.table(comment="Persisted ai_parse_document results, including per-page parsing errors.")
def parsed_documents():
    # Oversized/empty PDFs stay in bronze and appear in processing_status.
    return (
        spark.readStream.table("bronze_documents")
        .where((F.col("file_size_bytes") > 0) & (F.col("file_size_bytes") <= MAX_PDF_BYTES))
        .select(
            *IDENTITY_COLUMNS,
            F.expr("ai_parse_document(content, map('version', '2.0'))").alias("parsed"),
        )
    )


@dp.table(comment="Persisted search preparation and configurable ai_extract metadata results.")
def prepared_documents():
    return (
        spark.readStream.table("parsed_documents")
        .withColumn("parse_error", error_text("parsed:error_status"))
        .where(F.col("parsed").isNotNull() & F.col("parse_error").isNull())
        .select(
            *IDENTITY_COLUMNS,
            F.expr("size(variant_get(parsed, '$.document.pages', 'ARRAY<VARIANT>'))").alias("page_count"),
            F.expr("ai_prep_search(parsed, map('version', '2.0'))").alias("prepared"),
            F.call_function(
                "ai_extract", F.col("parsed"), F.lit(EXTRACTION_SCHEMA),
                F.create_map(F.lit("version"), F.lit("2.0")),
            ).alias("extracted"),
        )
    )


@dp.table(
    comment="One search-ready row per chunk. Page numbers are one-based physical PDF pages.",
    table_properties={"delta.enableChangeDataFeed": "true"},
)
def document_chunks():
    documents = (
        spark.readStream.table("prepared_documents")
        .withColumn("prep_error", error_text("prepared:error_status"))
        .where(F.col("prepared").isNotNull() & F.col("prep_error").isNull())
        .withColumn(
            "chunk", F.explode(F.expr("variant_get(prepared, '$.document.contents', 'ARRAY<VARIANT>')"))
        )
        .withColumn("chunk_position", F.expr("variant_get(chunk, '$.chunk_position', 'INT')"))
        .withColumn("chunk_to_retrieve", F.expr("variant_get(chunk, '$.chunk_to_retrieve', 'STRING')"))
        .withColumn("chunk_to_embed", F.expr("variant_get(chunk, '$.chunk_to_embed', 'STRING')"))
        .withColumn("chunk_pages", F.expr("variant_get(chunk, '$.pages', 'ARRAY<STRUCT<page_id:INT,image_uri:STRING>>')"))
        .withColumn("page_numbers", F.expr("transform(chunk_pages, p -> p.page_id + 1)"))
    )
    return documents.select(
        # Include source identity so even identical PDFs at different paths cannot collide.
        F.sha2(F.concat_ws("\n", "document_id", F.col("chunk_position").cast("string")), 256).alias("chunk_id"),
        *IDENTITY_COLUMNS, "chunk_position", "chunk_to_retrieve", "chunk_to_embed", "page_count",
        F.array_min("page_numbers").alias("page_start"),
        F.array_max("page_numbers").alias("page_end"),
        F.coalesce(F.expr("try_variant_get(extracted, '$.response.title', 'STRING')"), F.col("filename")).alias("title"),
        F.expr("try_variant_get(extracted, '$.response.summary', 'STRING')").alias("summary"),
        F.expr("try_variant_get(extracted, '$.response.topics', 'ARRAY<STRING>')").alias("topics"),
        error_text("extracted:error_message").alias("extraction_error"),
    ).where(
        F.col("chunk_position").isNotNull()
        & (F.length(F.trim("chunk_to_retrieve")) > 0)
        & (F.length(F.trim("chunk_to_embed")) > 0)
    )


@dp.materialized_view(comment="One row per source PDF showing readiness, failures, and raw AI error details.")
def document_processing_status():
    bronze = spark.read.table("bronze_documents").drop("content")
    parsed = spark.read.table("parsed_documents").select(
        "document_id", F.col("parsed").isNotNull().alias("has_parse_result"),
        error_text("parsed:error_status").alias("parse_error"),
    )
    prepared = spark.read.table("prepared_documents").select(
        "document_id", "page_count", F.col("prepared").isNotNull().alias("has_prep_result"),
        error_text("prepared:error_status").alias("prep_error"),
        error_text("extracted:error_message").alias("extraction_error"),
        F.col("extracted").isNotNull().alias("has_extraction_result"),
    )
    counts = spark.read.table("document_chunks").groupBy("document_id").agg(F.count("*").alias("chunk_count"))
    return (
        bronze.join(parsed, "document_id", "left")
        .join(prepared, "document_id", "left")
        .join(counts, "document_id", "left")
        .withColumn("chunk_count", F.coalesce("chunk_count", F.lit(0)))
        .withColumn(
            "status",
            F.when(F.col("file_size_bytes") <= 0, "empty_file")
            .when(F.col("file_size_bytes") > MAX_PDF_BYTES, "file_too_large")
            .when(~F.coalesce("has_parse_result", F.lit(False)), "parse_missing")
            .when(F.col("parse_error").isNotNull(), "parse_error")
            .when(~F.coalesce("has_prep_result", F.lit(False)), "prep_missing")
            .when(F.col("prep_error").isNotNull(), "prep_error")
            .when(F.col("chunk_count") == 0, "no_searchable_chunks")
            .when(
                F.col("extraction_error").isNotNull()
                | ~F.coalesce("has_extraction_result", F.lit(False)),
                "ready_with_metadata_error",
            )
            .otherwise("ready"),
        )
    )
