"""Tier 2 #8 integration tests — Workspace M2M changes fire the
debounced reindex bridge.

Drives real ``ws.tags.add()`` / ``.remove()`` / ``.clear()`` calls and
verifies the per-workspace debounce lock is acquired.  The locmem
cache backend provides real ``cache.add`` semantics; we patch only
the Celery ``.delay`` boundary so no broker is required.

See ``docs/plans/RAG_AUDIT_AND_ROADMAP.md`` Tier 2 #8.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.core.cache import cache


REINDEX_DELAY = (
    "components.knowledge.infrastructure.tasks.workspace_index_tasks."
    "reindex_workspace.delay"
)


@pytest.fixture(autouse=True)
def _flush_cache_between_tests():
    cache.clear()
    yield
    cache.clear()


def _cache_key(workspace_id) -> str:
    return f"knowledge:domain_reindex_v1:{workspace_id}"


@pytest.mark.django_db
class TestWorkspaceCategoryM2mTriggersReindex:
    def test_adding_a_category_acquires_debounce_lock(
        self, workspace_factory
    ):
        from infrastructure.persistence.workspaces.models import WorkspaceCategory

        workspace = workspace_factory()
        # The factory's own save already set the lock.  Clear it so we
        # observe the M2M signal in isolation.
        cache.clear()
        category = WorkspaceCategory.objects.create(name="A new category")
        with patch(REINDEX_DELAY):
            workspace.workspace_categories.add(category)

        assert cache.get(_cache_key(workspace.id)) == "1", (
            "Adding a category to the workspace must fire the M2M "
            "bridge and acquire the per-workspace debounce lock."
        )

    def test_removing_a_category_acquires_debounce_lock(
        self, workspace_factory
    ):
        from infrastructure.persistence.workspaces.models import WorkspaceCategory

        workspace = workspace_factory()
        category = WorkspaceCategory.objects.create(name="To be removed")
        with patch(REINDEX_DELAY):
            workspace.workspace_categories.add(category)
            cache.clear()
            workspace.workspace_categories.remove(category)

        assert cache.get(_cache_key(workspace.id)) == "1", (
            "Removing a category from the workspace must also fire "
            "the bridge — the snapshot needs to drop the category "
            "name from the classification section."
        )


@pytest.mark.django_db
class TestWorkspaceTagM2mTriggersReindex:
    def test_adding_a_tag_acquires_debounce_lock(self, workspace_factory):
        from infrastructure.persistence.workspaces.models import Tag

        workspace = workspace_factory()
        tag = Tag.objects.create(name="urgent")
        cache.clear()
        with patch(REINDEX_DELAY):
            workspace.tags.add(tag)

        assert cache.get(_cache_key(workspace.id)) == "1"


@pytest.mark.django_db
class TestM2mBridgeIsolation:
    def test_two_workspaces_get_independent_debounce_after_m2m_edit(
        self, workspace_factory
    ):
        from infrastructure.persistence.workspaces.models import Tag

        workspace_a = workspace_factory()
        workspace_b = workspace_factory()
        cache.clear()
        tag = Tag.objects.create(name="shared-tag")
        with patch(REINDEX_DELAY):
            workspace_a.tags.add(tag)
            workspace_b.tags.add(tag)

        assert cache.get(_cache_key(workspace_a.id)) == "1"
        assert cache.get(_cache_key(workspace_b.id)) == "1"

    def test_celery_broker_down_does_not_abort_m2m_add(
        self, workspace_factory
    ):
        from infrastructure.persistence.workspaces.models import Tag

        workspace = workspace_factory()
        tag = Tag.objects.create(name="some-tag")
        cache.clear()
        with patch(REINDEX_DELAY, side_effect=RuntimeError("broker down")):
            # Must not raise.
            workspace.tags.add(tag)

        # The M2M write itself committed regardless.
        assert workspace.tags.filter(pk=tag.pk).exists()
