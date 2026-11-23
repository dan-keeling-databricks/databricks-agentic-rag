"""Retrieve text and its page references from the managed AI Search index."""

import mlflow

SEARCH_COLUMNS = [
    "chunk_id", "chunk_to_retrieve", "source_path", "filename", "page_start", "page_end",
]


def decode_search_results(response):
    """Read the API's column manifest instead of relying on column positions."""
    data = response.as_dict() if hasattr(response, "as_dict") else response
    names = [column["name"] for column in data.get("manifest", {}).get("columns", [])]
    documents = []
    for row in data.get("result", {}).get("data_array", []) or []:
        item = dict(zip(names, row))
        content = item.get("chunk_to_retrieve")
        # A source without known page provenance cannot support a page citation.
        start, end = item.get("page_start"), item.get("page_end")
        if not content or not item.get("chunk_id") or not item.get("filename"):
            continue
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            continue
        documents.append({
            "content": content,
            "chunk_id": str(item["chunk_id"]),
            "filename": item["filename"],
            "source_path": item.get("source_path", ""),
            "page_start": start,
            "page_end": end,
        })
    return documents


class Retriever:
    def __init__(self, workspace_client, settings):
        self.workspace = workspace_client
        self.settings = settings

    @mlflow.trace(name="search_documents", span_type="RETRIEVER")
    def search(self, query):
        response = self.workspace.vector_search_indexes.query_index(
            index_name=self.settings.vector_search_index,
            columns=SEARCH_COLUMNS,
            query_text=query,
            query_type="HYBRID",
            num_results=self.settings.retrieval_k,
        )
        documents = decode_search_results(response)
        # Standard document shape makes retrieved text visible to MLflow scorers.
        span = mlflow.get_current_active_span()
        if span:
            span.set_outputs([
                {"page_content": item["content"], "metadata": {k: v for k, v in item.items() if k != "content"}}
                for item in documents
            ])
        return documents
