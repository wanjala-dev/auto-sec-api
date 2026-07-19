"""Integration tests for :class:`OrmWorkspaceRoleRepository`.

Migrations are disabled in the pytest suite (see ``conftest.py``), but
a session-wide autouse fixture (``default_system_roles``) materialises
the ``0016_seed_system_roles`` rows so RBAC tests have a consistent
role table. These repository tests therefore run against a DB that
already has the 8 seeded system roles — we use ``update_or_create``
to set the permissions we want for the assertion, and compare on
subsets rather than exact equality when a test could otherwise be
foiled by the pre-seeded rows.
"""

from __future__ import annotations

import pytest

from components.membership.infrastructure.repositories.workspace_role_repository import (
    OrmWorkspaceRoleRepository,
)


@pytest.fixture
def repo() -> OrmWorkspaceRoleRepository:
    return OrmWorkspaceRoleRepository()


@pytest.fixture
def role_model():
    from infrastructure.persistence.workspaces.models import WorkspaceRole

    return WorkspaceRole


@pytest.mark.django_db
class TestGetBySlug:
    def test_returns_system_role_when_no_workspace(self, repo, role_model) -> None:
        role_model.objects.update_or_create(
            slug="admin",
            workspace=None,
            defaults={
                "name": "Admin",
                "description": "Workspace admin",
                "permissions": ["manage_settings", "manage_users"],
                "is_system": True,
            },
        )
        entity = repo.get_by_slug("admin")
        assert entity is not None
        assert entity.slug == "admin"
        assert entity.is_system is True
        assert entity.workspace_id is None
        assert entity.permissions == frozenset({"manage_settings", "manage_users"})

    def test_returns_none_for_unknown_slug(self, repo) -> None:
        assert repo.get_by_slug("nonexistent") is None

    def test_prefers_workspace_custom_over_system_for_same_slug(
        self, repo, role_model, workspace_factory
    ) -> None:
        ws = workspace_factory()
        role_model.objects.create(
            slug="finance",
            name="Finance (system)",
            permissions=["view_budgets"],
            is_system=True,
            workspace=None,
        )
        role_model.objects.create(
            slug="finance",
            name="Finance (custom)",
            permissions=["manage_budgets", "manage_donations"],
            is_system=False,
            workspace=ws,
        )

        entity = repo.get_by_slug("finance", workspace_id=ws.id)
        assert entity is not None
        assert entity.name == "Finance (custom)"
        assert entity.is_system is False
        assert entity.workspace_id == ws.id

    def test_falls_back_to_system_when_no_custom(
        self, repo, role_model, workspace_factory
    ) -> None:
        ws = workspace_factory()
        role_model.objects.create(
            slug="auditor",
            name="Auditor",
            permissions=["view_donations"],
            is_system=True,
            workspace=None,
        )

        entity = repo.get_by_slug("auditor", workspace_id=ws.id)
        assert entity is not None
        assert entity.is_system is True
        assert entity.workspace_id is None


@pytest.mark.django_db
class TestGetById:
    def test_returns_entity_for_existing_role(self, repo, role_model) -> None:
        row = role_model.objects.create(
            slug="viewer",
            name="Viewer",
            permissions=["view_reports"],
            is_system=True,
            workspace=None,
        )
        entity = repo.get_by_id(row.id)
        assert entity is not None
        assert entity.id == row.id

    def test_returns_none_for_missing_id(self, repo) -> None:
        from uuid import uuid4

        assert repo.get_by_id(uuid4()) is None


@pytest.mark.django_db
class TestListSystemRoles:
    def test_returns_only_system_roles(
        self, repo, role_model, workspace_factory
    ) -> None:
        """System-role listing must exclude workspace-scoped custom roles.

        The 8 seeded system roles are already present; we only need to
        assert the custom row is filtered out and every returned row
        carries ``is_system=True``.
        """
        ws = workspace_factory()
        role_model.objects.create(
            slug="custom",
            name="Custom",
            permissions=["view_budgets"],
            is_system=False,
            workspace=ws,
        )

        roles = repo.list_system_roles()
        slugs = {r.slug for r in roles}
        assert "custom" not in slugs
        assert "admin" in slugs
        assert "viewer" in slugs
        assert all(r.is_system for r in roles)


@pytest.mark.django_db
class TestListAvailableForWorkspace:
    def test_returns_system_plus_own_custom_roles(
        self, repo, role_model, workspace_factory
    ) -> None:
        """Available list = all system roles + this workspace's custom roles only.

        The 8 seeded system roles are already present via conftest; we add
        one custom role per workspace and assert the cross-workspace
        isolation (ws_b's custom role must NOT appear for ws_a).
        """
        ws_a = workspace_factory()
        ws_b = workspace_factory()

        role_model.objects.create(
            slug="contractor",
            name="Contractor",
            permissions=["view_events"],
            is_system=False,
            workspace=ws_a,
        )
        role_model.objects.create(
            slug="steward",
            name="Steward",
            permissions=["view_donations"],
            is_system=False,
            workspace=ws_b,
        )

        available = repo.list_available_for_workspace(ws_a.id)
        slugs = {r.slug for r in available}
        assert "admin" in slugs  # system roles included
        assert "contractor" in slugs  # ws_a's own custom role
        assert "steward" not in slugs  # ws_b's custom role must not leak
