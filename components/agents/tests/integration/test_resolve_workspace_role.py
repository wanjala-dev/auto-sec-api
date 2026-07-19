"""SEE-199 — effective-role resolution for role-scoped retrieval.

``resolve_workspace_role`` is what turns an actor into the ``viewer_role`` the
retrieval port scopes on. It must mirror ``requires_role`` (ADR 0002): the
workspace owner resolves to ``owner`` without a membership row, an active member
resolves to its role, and a non-member resolves to ``None`` (least privilege).
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.base import (
    resolve_workspace_role,
)
from infrastructure.persistence.workspaces.models import WorkspaceMembership


@pytest.mark.django_db
class TestResolveWorkspaceRole:
    def test_workspace_owner_resolves_to_owner(self, workspace_factory):
        workspace = workspace_factory()

        role = resolve_workspace_role(workspace.workspace_owner_id, workspace.id)

        assert role == "owner"

    def test_active_member_resolves_to_its_role(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        member = user_factory()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=member,
            role=WorkspaceMembership.Role.MEMBER,
            status=WorkspaceMembership.Status.ACTIVE,
        )

        role = resolve_workspace_role(member.id, workspace.id)

        assert role == "member"

    def test_non_member_resolves_to_none(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        stranger = user_factory()

        assert resolve_workspace_role(stranger.id, workspace.id) is None

    def test_inactive_membership_resolves_to_none(self, workspace_factory, user_factory):
        workspace = workspace_factory()
        member = user_factory()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=member,
            role=WorkspaceMembership.Role.ADMIN,
            status=WorkspaceMembership.Status.INVITED,
        )

        assert resolve_workspace_role(member.id, workspace.id) is None

    def test_missing_ids_resolve_to_none(self):
        assert resolve_workspace_role(None, "ws-1") is None
        assert resolve_workspace_role("user-1", None) is None
