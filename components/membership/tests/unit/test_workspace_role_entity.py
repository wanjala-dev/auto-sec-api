"""Unit tests for :class:`WorkspaceRoleEntity`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest

from components.membership.domain.entities.workspace_role_entity import (
    WorkspaceRoleEntity,
)


class TestConstruction:
    def test_construct_system_role_ok(self) -> None:
        role = WorkspaceRoleEntity(
            id=uuid4(),
            slug="admin",
            name="Admin",
            description="Workspace administrator",
            permissions=frozenset({"manage_settings", "manage_users"}),
            is_system=True,
            workspace_id=None,
        )
        assert role.is_system is True
        assert role.workspace_id is None
        assert role.permissions == frozenset({"manage_settings", "manage_users"})

    def test_construct_custom_role_ok(self) -> None:
        workspace_id = uuid4()
        role = WorkspaceRoleEntity(
            id=uuid4(),
            slug="contractor",
            name="Contractor",
            description="Short-term external worker",
            permissions=frozenset({"view_events"}),
            is_system=False,
            workspace_id=workspace_id,
        )
        assert role.is_system is False
        assert role.workspace_id == workspace_id

    def test_list_permissions_normalized_to_frozenset(self) -> None:
        role = WorkspaceRoleEntity(
            id=uuid4(),
            slug="member",
            name="Member",
            description="",
            permissions=["view_reports", "view_budgets", "view_reports"],  # type: ignore[arg-type]
            is_system=True,
            workspace_id=None,
        )
        assert isinstance(role.permissions, frozenset)
        assert role.permissions == frozenset({"view_reports", "view_budgets"})


class TestInvariants:
    def test_rejects_empty_slug(self) -> None:
        with pytest.raises(ValueError, match="slug is required"):
            WorkspaceRoleEntity(
                id=uuid4(),
                slug="",
                name="X",
                description="",
                permissions=frozenset(),
                is_system=True,
                workspace_id=None,
            )

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            WorkspaceRoleEntity(
                id=uuid4(),
                slug="x",
                name="",
                description="",
                permissions=frozenset(),
                is_system=True,
                workspace_id=None,
            )

    def test_rejects_system_role_with_workspace(self) -> None:
        with pytest.raises(ValueError, match="System roles must have workspace_id=None"):
            WorkspaceRoleEntity(
                id=uuid4(),
                slug="admin",
                name="Admin",
                description="",
                permissions=frozenset(),
                is_system=True,
                workspace_id=uuid4(),
            )

    def test_rejects_custom_role_without_workspace(self) -> None:
        with pytest.raises(ValueError, match="must carry a workspace_id"):
            WorkspaceRoleEntity(
                id=uuid4(),
                slug="custom",
                name="Custom",
                description="",
                permissions=frozenset(),
                is_system=False,
                workspace_id=None,
            )


class TestImmutability:
    def test_frozen(self) -> None:
        role = WorkspaceRoleEntity(
            id=uuid4(),
            slug="admin",
            name="Admin",
            description="",
            permissions=frozenset({"manage_settings"}),
            is_system=True,
            workspace_id=None,
        )
        with pytest.raises(FrozenInstanceError):
            role.name = "Another"  # type: ignore[misc]


class TestPermissionChecks:
    def _role(self, perms: set[str]) -> WorkspaceRoleEntity:
        return WorkspaceRoleEntity(
            id=uuid4(),
            slug="t",
            name="T",
            description="",
            permissions=frozenset(perms),
            is_system=True,
            workspace_id=None,
        )

    def test_has_permission_true(self) -> None:
        assert self._role({"manage_donations"}).has_permission("manage_donations")

    def test_has_permission_false(self) -> None:
        assert not self._role({"manage_donations"}).has_permission("manage_budgets")

    def test_has_any_true_when_at_least_one_matches(self) -> None:
        role = self._role({"view_reports"})
        assert role.has_any({"view_reports", "manage_budgets"})

    def test_has_any_false_when_no_match(self) -> None:
        role = self._role({"view_reports"})
        assert not role.has_any({"manage_budgets", "manage_donations"})

    def test_has_all_true_when_every_match(self) -> None:
        role = self._role({"a", "b", "c"})
        assert role.has_all({"a", "b"})

    def test_has_all_false_when_missing_one(self) -> None:
        role = self._role({"a", "b"})
        assert not role.has_all({"a", "c"})
