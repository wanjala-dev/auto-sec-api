"""Integration tests for the reindex Celery tasks.

Runs with ``CELERY_TASK_ALWAYS_EAGER = True`` (project-wide test setting
in ``conftest.py``), so ``.delay()`` executes inline.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest


class _FakeEmbeddings:
    def embed_documents(self, texts):
        return [[0.0] * 1536 for _ in texts]

    def embed_query(self, text):
        return [0.0] * 1536


@pytest.fixture
def _stub_embeddings():
    target = (
        "components.knowledge.infrastructure.factories.embeddings.factory."
        "EmbeddingsFactory.create_embeddings"
    )
    with patch(target, return_value=_FakeEmbeddings()):
        yield


def _clear_signal_indexed_chunks():
    """The Workspace.post_save reindex signal runs eagerly (Celery eager mode)
    when ``workspace_factory`` creates a workspace, so the workspace is already
    indexed before the task under test runs. Clear those chunks so the explicit
    reindex exercises a real index, not a no-op skip."""
    from infrastructure.persistence.ai.models import EmbeddingChunk

    EmbeddingChunk.objects.all().delete()


@pytest.mark.django_db
class TestReindexWorkspaceTask:
    def test_task_executes_and_returns_indexed_result(
        self, workspace_factory, _stub_embeddings
    ):
        from components.knowledge.infrastructure.tasks.workspace_index_tasks import (
            reindex_workspace,
        )

        workspace = workspace_factory(
            workspace_name="Task Org",
            workspace_story="Index me please.",
        )
        _clear_signal_indexed_chunks()
        # Call the task directly — eager mode would also work via .delay().
        result = reindex_workspace(str(workspace.id), False)

        assert result["status"] == "indexed"
        assert result["workspace_id"] == str(workspace.id)
        assert result["chunks_written"] >= 2
        assert result["content_hash"]

    def test_task_reports_skipped_when_content_unchanged(
        self, workspace_factory, _stub_embeddings
    ):
        from components.knowledge.infrastructure.tasks.workspace_index_tasks import (
            reindex_workspace,
        )

        workspace = workspace_factory(workspace_name="Stable Org")
        _clear_signal_indexed_chunks()

        first = reindex_workspace(str(workspace.id), False)
        second = reindex_workspace(str(workspace.id), False)

        assert first["status"] == "indexed"
        assert second["status"] == "skipped"
        assert second["content_hash"] == first["content_hash"]

    def test_task_reports_failed_for_missing_workspace(self, _stub_embeddings):
        from components.knowledge.infrastructure.tasks.workspace_index_tasks import (
            reindex_workspace,
        )

        result = reindex_workspace("00000000-0000-0000-0000-000000000000", False)
        assert result["status"] == "failed"


@pytest.mark.django_db
class TestReindexAllWorkspacesTask:
    def test_nightly_fan_out_dispatches_one_task_per_active_workspace(
        self, workspace_factory, _stub_embeddings
    ):
        from components.knowledge.infrastructure.tasks.workspace_index_tasks import (
            reindex_all_workspaces,
        )

        ws_a = workspace_factory(workspace_name="A")
        ws_b = workspace_factory(workspace_name="B")
        ws_inactive = workspace_factory(workspace_name="C")
        ws_inactive.is_active = False
        ws_inactive.save()

        target = (
            "components.knowledge.infrastructure.tasks.workspace_index_tasks."
            "reindex_workspace.delay"
        )
        with patch(target) as mock_delay:
            summary = reindex_all_workspaces(False)

        dispatched_ids = {call.args[0] for call in mock_delay.call_args_list}
        assert str(ws_a.id) in dispatched_ids
        assert str(ws_b.id) in dispatched_ids
        assert str(ws_inactive.id) not in dispatched_ids
        assert summary["dispatched"] == mock_delay.call_count
