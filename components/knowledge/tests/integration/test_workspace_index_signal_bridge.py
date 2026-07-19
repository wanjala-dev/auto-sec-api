"""Integration tests for the Workspace post_save → reindex signal pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.mark.django_db
class TestWorkspaceIndexSignalBridge:
    def test_saving_a_workspace_enqueues_reindex(self, workspace_factory):
        target = (
            "components.knowledge.infrastructure.tasks.workspace_index_tasks."
            "reindex_workspace.delay"
        )
        with patch(target) as mock_delay:
            workspace = workspace_factory(workspace_name="Sentinel Org")

            # The bridge fires on every save; the post-factory save is
            # what we assert against.  At least one call must reference
            # the workspace id.
            mock_delay.assert_any_call(str(workspace.id), False)

    def test_updating_a_workspace_enqueues_reindex(self, workspace_factory):
        workspace = workspace_factory(workspace_name="Sentinel Org")
        target = (
            "components.knowledge.infrastructure.tasks.workspace_index_tasks."
            "reindex_workspace.delay"
        )
        with patch(target) as mock_delay:
            workspace.workspace_story = "Story added after creation."
            workspace.save()

            mock_delay.assert_any_call(str(workspace.id), False)

    def test_signal_handler_swallows_handler_errors(self, workspace_factory):
        """A crashing enqueue must not break the Workspace.save() call."""
        target = (
            "components.knowledge.infrastructure.tasks.workspace_index_tasks."
            "reindex_workspace.delay"
        )
        with patch(target, side_effect=RuntimeError("broker down")):
            workspace = workspace_factory(workspace_name="Resilient Org")

        # If the handler didn't swallow the error, the save above would
        # have propagated it — reaching this line is the assertion.
        assert workspace.pk is not None
