"""Domain entity for a workspace role.

A role is a named bundle of capability keys. It is the RBAC enforcement
unit — a user's permissions in a workspace are the role's ``permissions``
set. See ADR 0002 for the persona/role split.

System roles have ``workspace_id=None`` and ``is_system=True``; they are
seeded from code and shared across every workspace. Workspace-scoped
custom roles carry a ``workspace_id`` and ``is_system=False``.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class WorkspaceRoleEntity:
    """Immutable representation of a workspace role."""

    id: UUID
    slug: str
    name: str
    description: str
    permissions: frozenset[str]
    is_system: bool
    workspace_id: UUID | None = None
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None

    def __post_init__(self) -> None:
        if not self.slug:
            raise ValueError("WorkspaceRoleEntity.slug is required")
        if not self.name:
            raise ValueError("WorkspaceRoleEntity.name is required")
        if self.is_system and self.workspace_id is not None:
            raise ValueError(
                "System roles must have workspace_id=None "
                f"(got workspace_id={self.workspace_id!r} for slug={self.slug!r})"
            )
        if not self.is_system and self.workspace_id is None:
            raise ValueError(
                f"Custom role slug={self.slug!r} must carry a workspace_id"
            )
        # Ensure permissions is a frozenset of strings even when callers pass
        # a list/tuple/set — the frozen dataclass protects identity but not
        # the collection's type. __setattr__ is required because the class
        # is frozen.
        if not isinstance(self.permissions, frozenset):
            object.__setattr__(
                self, "permissions", frozenset(str(p) for p in self.permissions)
            )

    def has_permission(self, key: str) -> bool:
        """Return True if ``key`` is in this role's permission set."""
        return key in self.permissions

    def has_any(self, keys: "frozenset[str] | set[str] | list[str]") -> bool:
        """Return True if the role carries at least one of the given keys."""
        return any(key in self.permissions for key in keys)

    def has_all(self, keys: "frozenset[str] | set[str] | list[str]") -> bool:
        """Return True if the role carries every one of the given keys."""
        return all(key in self.permissions for key in keys)
