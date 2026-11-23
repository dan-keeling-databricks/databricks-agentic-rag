"""Small, deterministic checks that complement the AI judges.

These checks establish whether references are real and whether the expected
pages were retrieved. They do not establish whether a cited page supports a
claim; the groundedness judge assesses that separately.
"""

from __future__ import annotations

import json
import math
from pathlib import Path


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


def _covers(source: dict, filename: str, page: int) -> bool:
    try:
        return (
            source.get("filename") == filename
            and 1 <= int(source["page_start"]) <= page <= int(source["page_end"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def citation_validity(outputs: dict, expectations: dict) -> tuple[bool, str]:
    """Check that returned citations map to retrieved chunks and page ranges."""
    sources = outputs.get("sources") or []
    context = outputs.get("retrieved_context") or []
    if not sources:
        if not expectations.get("answerable", True):
            return True, "No citation is required when the expected behavior is abstention."
        return False, "An answerable question has no source references."
    invalid = []
    for source in sources:
        matching = [item for item in context if item.get("chunk_id") == source.get("chunk_id")]
        try:
            start, end = int(source["page_start"]), int(source["page_end"])
            valid = bool(source.get("chunk_id")) and start <= end and all(
                any(_covers(item, source.get("filename", ""), page) for item in matching)
                for page in (start, end)
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            invalid.append(source.get("chunk_id", "missing chunk_id"))
    if invalid:
        return False, f"References do not match retrieved document/page ranges: {invalid}"
    return True, "Every source reference maps to a retrieved chunk and valid page range."


def evidence_page_recall(outputs: dict, expectations: dict) -> tuple[float | None, str]:
    """Fraction of distinct benchmark document/pages covered by retrieved chunks."""
    expected_pages = {(item["filename"], int(item["page"])) for item in expectations.get("evidence", [])}
    if not expected_pages:
        return None, "Not applicable: this question expects abstention and has no evidence pages."
    context = outputs.get("retrieved_context") or []
    matched = {(name, page) for name, page in expected_pages if any(_covers(item, name, page) for item in context)}
    return len(matched) / len(expected_pages), f"Retrieved {len(matched)} of {len(expected_pages)} benchmark document/pages. Other pages may also be valid evidence."


def numeric_metrics(metrics: dict) -> dict[str, float]:
    """Keep report JSON portable; omit NaN/Infinity rather than inventing scores."""
    return {
        str(key): float(value)
        for key, value in metrics.items()
        if isinstance(value, (int, float)) and math.isfinite(float(value))
    }
