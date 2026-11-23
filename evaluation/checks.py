"""Validate benchmark seed records and identify the evaluated source files."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path


IMPLEMENTATION_FILES = (
    "src/rag/agent.py", "src/rag/retrieval.py", "src/rag/config.py",
    "src/pipeline/documents.sql",
)


def implementation_fingerprint(root: str | Path) -> dict:
    """Identify the evaluated source even when Jobs has no Git checkout metadata."""
    digest = hashlib.sha256()
    files = {}
    for relative_path in IMPLEMENTATION_FILES:
        content = (Path(root) / relative_path).read_bytes()
        digest.update(relative_path.encode("utf-8") + b"\0" + content + b"\0")
        files[relative_path] = hashlib.sha256(content).hexdigest()
    return {"implementation_sha256": digest.hexdigest(), "file_sha256": files}


def load_benchmark(path: str | Path) -> list[dict]:
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    identifiers = [record["id"] for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("Benchmark question IDs must be unique.")
    for record in records:
        if not record["inputs"]["query"].strip():
            raise ValueError(f"Empty query: {record['id']}")
        expected = record["expectations"]
        if not expected["expected_response"] or not expected["expected_facts"]:
            raise ValueError(f"Missing reference answer: {record['id']}")
        if expected["answerable"] and not expected["evidence"]:
            raise ValueError(f"Missing source evidence: {record['id']}")
    return records
