"""ORM adapter implementing UserOnboardingWorkspacePort.

Wraps the existing workspace bootstrap logic from apps/users/workspace_bootstrap.py
behind the workspace port contract, keeping ORM operations in infrastructure.
"""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.user_onboarding_workspace_port import (
    OnboardingWorkspaceResult,
    UserOnboardingWorkspacePort,
)


class UserOnboardingWorkspaceRepository(UserOnboardingWorkspacePort):
    """Concrete adapter backed by Django ORM for onboarding workspace ops."""

    def _get_user(self, user_id: UUID):
        from infrastructure.persistence.users.models import CustomUser
        return CustomUser.objects.get(id=user_id)

    def should_bootstrap(self, user_id: UUID) -> bool:
        from components.identity.infrastructure.adapters.workspace_bootstrap import should_bootstrap_workspace
        user = self._get_user(user_id)
        return should_bootstrap_workspace(user)

    def find_preferred_workspace_id(self, user_id: UUID) -> UUID | None:
        from components.identity.infrastructure.adapters.workspace_bootstrap import _preferred_workspace_for_user
        user = self._get_user(user_id)
        workspace = _preferred_workspace_for_user(user)
        return workspace.id if workspace else None

    def create_personal_workspace(self, user_id: UUID) -> OnboardingWorkspaceResult | None:
        from components.identity.infrastructure.adapters.workspace_bootstrap import _create_bootstrap_workspace
        user = self._get_user(user_id)
        workspace = _create_bootstrap_workspace(user)
        if workspace is None:
            return None
        return OnboardingWorkspaceResult(
            workspace_id=workspace.id,
            workspace_name=workspace.workspace_name,
            was_created=True,
        )

    def sync_profile_context(self, user_id: UUID, workspace_id: UUID, *, force: bool = False) -> None:
        from components.identity.infrastructure.adapters.workspace_bootstrap import _sync_profile_context
        from infrastructure.persistence.workspaces.models import Workspace
        user = self._get_user(user_id)
        workspace = Workspace.objects.get(id=workspace_id)
        _sync_profile_context(user, workspace, force_workspace=force)

    def ensure_follower(self, workspace_id: UUID, user_id: UUID) -> None:
        from components.workspace.application.facades.workspace_facade import ensure_workspace_follower
        from infrastructure.persistence.workspaces.models import Workspace
        user = self._get_user(user_id)
        workspace = Workspace.objects.get(id=workspace_id)
        ensure_workspace_follower(workspace, user)
