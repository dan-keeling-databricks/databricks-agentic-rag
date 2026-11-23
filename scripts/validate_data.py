"""Check the saved pipeline outputs and page provenance using a SQL warehouse."""

import argparse
import json
import re
import time

from databricks.sdk import WorkspaceClient


def statement(workspace, warehouse_id, sql):
    result = workspace.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=sql, wait_timeout="30s",
    )
    deadline = time.monotonic() + 90
    while result.status.state.value in {"PENDING", "RUNNING"} and time.monotonic() < deadline:
        time.sleep(2)
        result = workspace.statement_execution.get_statement(result.statement_id)
    if result.status.state.value != "SUCCEEDED":
        raise RuntimeError(str(result.status.as_dict()))
    return result.result.data_array or []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["profile", "catalog", "warehouse-id"]:
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--schema", default="agentic_rag")
    parser.add_argument("--expected-documents", type=int)
    args = parser.parse_args()
    for part in [args.catalog, args.schema]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", part):
            raise ValueError("Catalog and schema must be plain Unity Catalog identifiers")
    prefix = f"`{args.catalog}`.`{args.schema}`"
    workspace = WorkspaceClient(profile=args.profile)
    status = statement(workspace, args.warehouse_id,
                       f"SELECT status, count(*) FROM {prefix}.document_processing_status GROUP BY status")
    counts = statement(workspace, args.warehouse_id, f"""
      SELECT count(*) AS chunks, count(DISTINCT chunk_id) AS unique_chunks,
             count_if(page_start IS NULL OR page_end IS NULL OR page_start < 1 OR page_end < page_start) AS bad_pages
      FROM {prefix}.document_chunks
    """)[0]
    stages = {}
    for table in ["bronze_documents", "parsed_documents", "prepared_documents"]:
        stages[table] = int(statement(workspace, args.warehouse_id, f"SELECT count(*) FROM {prefix}.{table}")[0][0])
    report = {"document_status": dict(status), "stages": stages,
              "chunks": int(counts[0]), "unique_chunks": int(counts[1]), "invalid_page_references": int(counts[2])}
    print(json.dumps(report, indent=2))
    if any(name != "ready" and int(count) for name, count in status):
        raise RuntimeError("Some PDFs need attention; inspect document_processing_status")
    if args.expected_documents and any(count != args.expected_documents for count in stages.values()):
        raise RuntimeError("Not every expected PDF completed all persisted AI stages")
    if report["chunks"] < 1 or report["chunks"] != report["unique_chunks"] or report["invalid_page_references"]:
        raise RuntimeError("Search chunks are missing, duplicated, or lack valid page references")


if __name__ == "__main__":
    main()
