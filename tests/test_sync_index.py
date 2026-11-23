"""A queryable index must not be mistaken for a fresh, successfully synced index."""

from unittest.mock import Mock

import pytest
from databricks.sdk.errors import NotFound
from databricks.sdk.service.pipelines import ListUpdatesResponse, UpdateInfo, UpdateInfoState
from databricks.sdk.service.vectorsearch import (
    DeltaSyncVectorIndexSpecResponse, IndexStatus, VectorIndex, VectorIndexStatus,
)

from scripts import sync_index


def index(state=IndexStatus.ONLINE_NO_PENDING_UPDATE, ready=True, pipeline_id="backing-pipeline"):
    return VectorIndex(
        delta_sync_index_spec=DeltaSyncVectorIndexSpecResponse(
            source_table="catalog.rag.document_chunks", pipeline_id=pipeline_id,
        ),
        status=VectorIndexStatus(detailed_state=state, ready=ready),
    )


def updates(update_id="old", state=UpdateInfoState.COMPLETED):
    return ListUpdatesResponse(updates=[UpdateInfo(update_id=update_id, state=state)])


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(sync_index.time, "sleep", lambda _: None)


def refresh(workspace, **kwargs):
    return sync_index.refresh_index(
        workspace, "catalog.rag.search", "catalog.rag.document_chunks", "search", "embeddings", **kwargs
    )


def test_stale_ready_status_does_not_complete_new_sync():
    workspace = Mock()
    workspace.vector_search_indexes.get_index.return_value = index()
    workspace.pipelines.list_updates.side_effect = [
        updates(),  # Snapshot before sync.
        updates(),  # API still reports the previous completed update.
        updates("new", UpdateInfoState.RUNNING),
        updates("new", UpdateInfoState.COMPLETED),
    ]
    result = refresh(workspace)
    assert result.status.ready
    assert workspace.pipelines.list_updates.call_count == 4
    workspace.vector_search_indexes.sync_index.assert_called_once_with("catalog.rag.search")


def test_fast_sync_can_complete_between_polls_without_observed_busy_state():
    workspace = Mock()
    workspace.vector_search_indexes.get_index.return_value = index()
    workspace.pipelines.list_updates.side_effect = [updates(), updates("fast-new")]
    refresh(workspace)
    assert workspace.vector_search_indexes.get_index.call_count == 2


@pytest.mark.parametrize("state", [IndexStatus.OFFLINE_FAILED, IndexStatus.ONLINE_PIPELINE_FAILED])
def test_queryable_but_failed_index_fails_immediately(state):
    workspace = Mock()
    workspace.vector_search_indexes.get_index.side_effect = [index(), index(state, ready=True)]
    workspace.pipelines.list_updates.return_value = updates()
    with pytest.raises(RuntimeError, match="update failed"):
        refresh(workspace)


@pytest.mark.parametrize("state", [UpdateInfoState.FAILED, UpdateInfoState.CANCELED])
def test_new_failed_pipeline_update_is_not_hidden_by_ready_index(state):
    workspace = Mock()
    workspace.vector_search_indexes.get_index.return_value = index()
    workspace.pipelines.list_updates.side_effect = [updates(), updates("new", state)]
    with pytest.raises(RuntimeError, match=f"ended with {state.value}"):
        refresh(workspace)


def test_creation_waits_for_backing_pipeline_and_index_readiness():
    workspace = Mock()
    workspace.vector_search_indexes.get_index.side_effect = [
        NotFound("missing"), index(IndexStatus.PROVISIONING, False, None),
        index(IndexStatus.PROVISIONING_INITIAL_SNAPSHOT, False), index(),
    ]
    workspace.pipelines.list_updates.side_effect = [
        updates("initial", UpdateInfoState.RUNNING), updates("initial"),
    ]
    refresh(workspace)
    workspace.vector_search_indexes.create_index.assert_called_once()
    workspace.vector_search_indexes.sync_index.assert_not_called()


def test_ready_without_fresh_completed_update_times_out(monkeypatch):
    workspace = Mock()
    workspace.vector_search_indexes.get_index.return_value = index()
    workspace.pipelines.list_updates.return_value = updates()
    monkeypatch.setattr(sync_index.time, "monotonic", Mock(side_effect=[0, 0, 2]))
    with pytest.raises(TimeoutError, match="fresh sync"):
        refresh(workspace, timeout=1)


def test_completed_pipeline_still_waits_until_index_is_queryable():
    workspace = Mock()
    workspace.vector_search_indexes.get_index.side_effect = [
        index(), index(IndexStatus.ONLINE_TRIGGERED_UPDATE, ready=False), index(),
    ]
    workspace.pipelines.list_updates.side_effect = [updates(), updates("new"), updates("new")]
    refresh(workspace)
    assert workspace.vector_search_indexes.get_index.call_count == 3


def test_wrong_source_table_is_rejected_without_sync():
    workspace = Mock()
    existing = index()
    existing.delta_sync_index_spec.source_table = "different.table.source"
    workspace.vector_search_indexes.get_index.return_value = existing
    with pytest.raises(ValueError, match="another source table"):
        refresh(workspace)
    workspace.vector_search_indexes.sync_index.assert_not_called()
