"""Tier 2 #8 — unit tests for the Workspace M2M reindex use case.

Pure application-layer tests with mocked instances; no DB, no Django
signals fired.  See
``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #8.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from components.knowledge.application.use_cases.enqueue_workspace_m2m_change_reindex_use_case import (
    EnqueueWorkspaceM2mChangeReindexUseCase,
    _resolve_workspace_ids,
)


class TestResolveWorkspaceIds:
    def test_forward_direction_returns_instance_id(self):
        instance = SimpleNamespace(id="ws-1", pk="ws-1")
        ids = _resolve_workspace_ids(
            instance=instance, pk_set={"tag-a", "tag-b"}, reverse=False
        )
        assert ids == ("ws-1",)

    def test_reverse_direction_returns_pk_set(self):
        instance = SimpleNamespace(id="tag-a", pk="tag-a")
        ids = _resolve_workspace_ids(
            instance=instance, pk_set={"ws-1", "ws-2"}, reverse=True
        )
        # Order isn't guaranteed (set membership), but membership is.
        assert sorted(ids) == ["ws-1", "ws-2"]

    def test_post_clear_in_reverse_direction_returns_empty(self):
        """post_clear carries pk_set=None — Django doesn't know what
        was cleared.  Best-effort fallback is empty (the nightly beat
        heals it)."""
        instance = SimpleNamespace(id="tag-a")
        ids = _resolve_workspace_ids(
            instance=instance, pk_set=None, reverse=True
        )
        assert tuple(ids) == ()

    def test_forward_direction_with_no_instance_id_returns_empty(self):
        instance = SimpleNamespace(id=None, pk=None)
        ids = _resolve_workspace_ids(
            instance=instance, pk_set={"x"}, reverse=False
        )
        assert tuple(ids) == ()


class TestExecuteRoutesToDebounceHelper:
    @staticmethod
    def _make_use_case():
        return EnqueueWorkspaceM2mChangeReindexUseCase(m2m_label="tags")

    def test_post_add_dispatches_for_forward_workspace(self):
        instance = SimpleNamespace(id="ws-1", pk="ws-1")
        with patch(
            "components.knowledge.application.use_cases."
            "enqueue_workspace_m2m_change_reindex_use_case."
            "enqueue_reindex_for_workspace"
        ) as mock_helper:
            self._make_use_case().execute(
                action="post_add",
                instance=instance,
                pk_set={"tag-a"},
                reverse=False,
            )
        mock_helper.assert_called_once()
        args, kwargs = mock_helper.call_args
        assert args == ("ws-1",)
        assert kwargs["domain_label"] == "workspace_m2m:tags"

    def test_pre_add_is_ignored(self):
        """We only react to post-* actions — pre-* would race the row
        write."""
        instance = SimpleNamespace(id="ws-1", pk="ws-1")
        with patch(
            "components.knowledge.application.use_cases."
            "enqueue_workspace_m2m_change_reindex_use_case."
            "enqueue_reindex_for_workspace"
        ) as mock_helper:
            self._make_use_case().execute(
                action="pre_add",
                instance=instance,
                pk_set={"tag-a"},
                reverse=False,
            )
        mock_helper.assert_not_called()

    def test_reverse_post_add_dispatches_for_each_workspace(self):
        instance = SimpleNamespace(id="tag-a", pk="tag-a")
        with patch(
            "components.knowledge.application.use_cases."
            "enqueue_workspace_m2m_change_reindex_use_case."
            "enqueue_reindex_for_workspace"
        ) as mock_helper:
            self._make_use_case().execute(
                action="post_add",
                instance=instance,
                pk_set={"ws-1", "ws-2"},
                reverse=True,
            )
        # Two workspaces affected → two helper invocations.
        assert mock_helper.call_count == 2
        call_args = {call.args[0] for call in mock_helper.call_args_list}
        assert call_args == {"ws-1", "ws-2"}
