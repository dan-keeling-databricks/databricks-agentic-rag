"""Optional live SQL contract checks against an explicitly selected deployment.

Set SQL_TEST_PROFILE, SQL_TEST_WAREHOUSE_ID, and SQL_TEST_CATALOG to run these.
SQL_TEST_SCHEMA defaults to agentic_rag. No AI functions are called by these tests.
"""

import os
from pathlib import Path
import re

import pytest

from scripts.validate_data import statement

SOURCE = Path(__file__).parents[1] / "src/pipeline/documents.sql"


@pytest.fixture
def deployment():
    names = ("SQL_TEST_PROFILE", "SQL_TEST_WAREHOUSE_ID", "SQL_TEST_CATALOG")
    if not all(os.getenv(name) for name in names):
        pytest.skip("Set SQL_TEST_PROFILE, SQL_TEST_WAREHOUSE_ID, and SQL_TEST_CATALOG for live SQL checks.")
    from databricks.sdk import WorkspaceClient
    catalog = os.environ["SQL_TEST_CATALOG"]
    schema = os.getenv("SQL_TEST_SCHEMA", "agentic_rag")
    if not all(re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in (catalog, schema)):
        raise ValueError("Use plain Unity Catalog catalog/schema identifiers.")
    return (WorkspaceClient(profile=os.environ["SQL_TEST_PROFILE"]),
            os.environ["SQL_TEST_WAREHOUSE_ID"], f"`{catalog}`.`{schema}`")


def pipeline_query(name):
    # Split on the next dataset definition, not semicolons inside SQL comments.
    match = re.search(
        r"CREATE OR REFRESH (?:STREAMING TABLE|MATERIALIZED VIEW) " + name
        + r"\b.*?\nAS\n(.*?)(?=\nCREATE OR REFRESH|\Z)", SOURCE.read_text(), re.S,
    )
    assert match, name
    return re.sub(r"STREAM\((\w+)\)", r"\1", match[1].strip().removesuffix(";"))


@pytest.mark.parametrize("table", ["document_chunks", "document_processing_status"])
def test_sql_projection_matches_saved_rows(deployment, table):
    workspace, warehouse, prefix = deployment
    query = pipeline_query(table)
    for name in ("bronze_documents", "parsed_documents", "prepared_documents", "document_chunks"):
        query = re.sub(r"\bFROM " + name + r"\b", "FROM " + prefix + "." + name, query)
    sql = f"""WITH candidate AS ({query}), expected AS (SELECT * FROM {prefix}.{table})
      SELECT (SELECT count(*) FROM (SELECT * FROM candidate EXCEPT ALL SELECT * FROM expected)),
             (SELECT count(*) FROM (SELECT * FROM expected EXCEPT ALL SELECT * FROM candidate))"""
    assert [int(value) for value in statement(workspace, warehouse, sql)[0]] == [0, 0]


def test_processing_status_covers_failures_and_empty_error_values(deployment):
    workspace, warehouse, _ = deployment
    fixtures='''WITH examples(id, bytes, parsed_json, prepared_json, extracted_json, chunks, expected) AS (VALUES
     ('empty',0,NULL,NULL,NULL,0,'empty_file'),
     ('oversized',100000001,NULL,NULL,NULL,0,'file_too_large'),
     ('parse_missing',1,NULL,NULL,NULL,0,'parse_missing'),
     ('parse_failed',1,'{"error_status":["bad page"]}',NULL,NULL,0,'parse_error'),
     ('prep_missing',1,'{}',NULL,NULL,0,'prep_missing'),
     ('prep_failed',1,'{}','{"error_status":{"message":"bad prep"}}',NULL,0,'prep_error'),
     ('empty_chunks',1,'{}','{}','{}',0,'no_searchable_chunks'),
     ('metadata_missing',1,'{}','{}',NULL,1,'ready_with_metadata_error'),
     ('metadata_failed',1,'{}','{}','{"error_message":"bad metadata"}',1,'ready_with_metadata_error'),
     ('ready',1,'{"error_status":[]}','{"error_status":{}}','{"error_message":null}',1,'ready'),
     ('empty_error',1,'{"error_status":""}','{"error_status":"null"}','{"error_message":[]}',1,'ready')
    ), bronze_documents AS (
     SELECT id AS document_id,id AS source_path,id AS filename,id AS content_sha256,
     CAST(bytes AS BIGINT) AS file_size_bytes,CAST(NULL AS TIMESTAMP) AS file_modified_at,
     CAST(NULL AS TIMESTAMP) AS ingested_at FROM examples
    ), parsed_documents AS (
     SELECT id AS document_id,parse_json(parsed_json) AS parsed FROM examples
    ), prepared_documents AS (
     SELECT id AS document_id,CAST(1 AS INT) AS page_count,
     parse_json(prepared_json) AS prepared,parse_json(extracted_json) AS extracted FROM examples
    ), document_chunks AS (SELECT id AS document_id FROM examples WHERE chunks>0),'''
    query = pipeline_query("document_processing_status").lstrip()
    assert query.startswith("WITH ")
    sql = (fixtures + " actual AS (WITH " + query[5:]
           + ") SELECT a.document_id,a.status,e.expected FROM actual a JOIN examples e ON a.document_id=e.id")
    rows = statement(workspace, warehouse, sql)
    assert len(rows) == 11
    assert all(actual == expected for _, actual, expected in rows), rows
