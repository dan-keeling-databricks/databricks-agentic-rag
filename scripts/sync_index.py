"""Create the search index after its source table exists, then refresh it.

The bundle owns the search endpoint. This small job handles the index because
Databricks requires the pipeline's source table to exist before index creation.
"""

import argparse
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.pipelines import UpdateInfoState
from databricks.sdk.service.vectorsearch import (
    DeltaSyncVectorIndexSpecRequest, EmbeddingSourceColumn, IndexStatus, PipelineType, VectorIndexType,
)


def latest_update(workspace, pipeline_id):
    """The API returns newest first; no result means no update is visible yet."""
    updates = workspace.pipelines.list_updates(pipeline_id, max_results=1).updates
    return updates[0] if updates else None


def refresh_index(workspace, index_name, source_table, endpoint, embedding_endpoint, timeout=1800):
    previous_update_id = None
    try:
        index = workspace.vector_search_indexes.get_index(index_name)
    except NotFound:
        index = workspace.vector_search_indexes.create_index(
            name=index_name, endpoint_name=endpoint, primary_key="chunk_id",
            index_type=VectorIndexType.DELTA_SYNC,
            delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
                source_table=source_table, pipeline_type=PipelineType.TRIGGERED,
                embedding_source_columns=[EmbeddingSourceColumn(
                    name="chunk_to_embed", embedding_model_endpoint_name=embedding_endpoint,
                )],
                columns_to_sync=["chunk_to_retrieve", "source_path", "filename", "page_start",
                                 "page_end", "title", "summary", "topics", "document_id"],
            ),
        )
        print(f"Created {index_name}", flush=True)
    else:
        spec = index.delta_sync_index_spec
        if not spec or spec.source_table != source_table:
            raise ValueError("Existing index points to another source table; choose a new index name")
        if not spec.pipeline_id:
            raise RuntimeError("Existing index has no backing pipeline ID; wait for provisioning before retrying")
        previous = latest_update(workspace, spec.pipeline_id)
        previous_update_id = previous.update_id if previous else None
        workspace.vector_search_indexes.sync_index(index_name)
        print(f"Refreshing {index_name}", flush=True)

    deadline = time.monotonic() + timeout
    last_status = "starting"
    while time.monotonic() < deadline:
        index = workspace.vector_search_indexes.get_index(index_name)
        status = index.status
        last_status = status.as_dict() if status else "starting"
        print(f"Index status: {last_status}", flush=True)
        if status and status.detailed_state in {
            IndexStatus.OFFLINE_FAILED, IndexStatus.ONLINE_PIPELINE_FAILED,
        }:
            raise RuntimeError(f"Index {index_name} update failed: {last_status}")

        spec = index.delta_sync_index_spec
        update = latest_update(workspace, spec.pipeline_id) if spec and spec.pipeline_id else None
        # ready=True only means queries are possible, including queries against stale
        # data. A completed update from before our sync request is not success.
        is_new_update = bool(update and update.update_id and update.update_id != previous_update_id)
        if is_new_update:
            if update.state in {UpdateInfoState.FAILED, UpdateInfoState.CANCELED}:
                raise RuntimeError(
                    f"Index {index_name} backing pipeline update {update.update_id} "
                    f"ended with {update.state.value}; inspect pipeline {spec.pipeline_id}"
                )
            if (
                update.state == UpdateInfoState.COMPLETED
                and status and status.ready
                and status.detailed_state in {IndexStatus.ONLINE_NO_PENDING_UPDATE, IndexStatus.ONLINE}
            ):
                return index
        time.sleep(10)
    raise TimeoutError(
        f"Index {index_name} did not complete a fresh sync within {timeout} seconds; "
        f"last status: {last_status}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["index", "source-table", "endpoint", "embedding-endpoint"]:
        parser.add_argument(f"--{name}", required=True)
    # Omit only inside Databricks Jobs, where the runtime provides its identity.
    parser.add_argument("--profile")
    args = parser.parse_args()
    workspace = WorkspaceClient(profile=args.profile) if args.profile else WorkspaceClient()
    refresh_index(workspace, args.index, args.source_table, args.endpoint, args.embedding_endpoint)


if __name__ == "__main__":
    main()
