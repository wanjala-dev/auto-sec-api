"""Integration tests for the ``reindex_workspaces`` management command."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command


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
    indexed before the command/task under test runs. Clear those chunks so the
    explicit reindex exercises a real index, not a no-op skip."""
    from infrastructure.persistence.ai.models import EmbeddingChunk

    EmbeddingChunk.objects.all().delete()


@pytest.mark.django_db
class TestReindexWorkspacesCommand:
    def test_requires_a_scope_flag(self):
        with pytest.raises(CommandError):
            call_command("reindex_workspaces")

    def test_sync_single_workspace(self, workspace_factory, _stub_embeddings):
        workspace = workspace_factory(workspace_name="CLI Org")
        _clear_signal_indexed_chunks()
        out = StringIO()
        call_command(
            "reindex_workspaces",
            "--workspace",
            str(workspace.id),
            "--sync",
            stdout=out,
        )
        output = out.getvalue()
        assert str(workspace.id) in output
        assert "status=indexed" in output

    def test_single_workspace_unknown_id_raises(self):
        with pytest.raises(CommandError):
            call_command(
                "reindex_workspaces",
                "--workspace",
                "00000000-0000-0000-0000-000000000000",
                "--sync",
            )

    def test_sync_all_reports_per_workspace_and_summary(
        self, workspace_factory, _stub_embeddings
    ):
        workspace_factory(workspace_name="A")
        workspace_factory(workspace_name="B")
        _clear_signal_indexed_chunks()
        out = StringIO()
        call_command("reindex_workspaces", "--all", "--sync", stdout=out)
        output = out.getvalue()
        assert output.count("→ indexed") >= 2
        assert "Done:" in output

    def test_async_single_queues_task(self, workspace_factory):
        workspace = workspace_factory(workspace_name="Async Org")
        target = (
            "components.knowledge.infrastructure.tasks.workspace_index_tasks."
            "reindex_workspace.delay"
        )
        with patch(target) as mock_delay:
            mock_delay.return_value.id = "task-123"
            out = StringIO()
            call_command(
                "reindex_workspaces",
                "--workspace",
                str(workspace.id),
                stdout=out,
            )
        mock_delay.assert_called_with(str(workspace.id), False)
        assert "queued" in out.getvalue()

    def test_async_all_queues_fanout_task(self, workspace_factory):
        workspace_factory(workspace_name="A")
        target = (
            "components.knowledge.infrastructure.tasks.workspace_index_tasks."
            "reindex_all_workspaces.delay"
        )
        with patch(target) as mock_delay:
            mock_delay.return_value.id = "fanout-456"
            out = StringIO()
            call_command("reindex_workspaces", "--all", stdout=out)
        mock_delay.assert_called_once_with(False)
        assert "queued reindex_all_workspaces" in out.getvalue()
