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
        from components.identity.application.providers.workspace_bootstrap_provider import get_workspace_bootstrap_provider
        user = self._get_user(user_id)
        return get_workspace_bootstrap_provider().should_bootstrap_workspace(user)

    def find_preferred_workspace_id(self, user_id: UUID) -> UUID | None:
        from components.identity.application.providers.workspace_bootstrap_provider import get_workspace_bootstrap_provider
        user = self._get_user(user_id)
        workspace = get_workspace_bootstrap_provider().preferred_workspace_for_user(user)
        return workspace.id if workspace else None

    def create_personal_workspace(self, user_id: UUID) -> OnboardingWorkspaceResult | None:
        from components.identity.application.providers.workspace_bootstrap_provider import get_workspace_bootstrap_provider
        user = self._get_user(user_id)
        workspace = get_workspace_bootstrap_provider().create_bootstrap_workspace(user)
        if workspace is None:
            return None
        return OnboardingWorkspaceResult(
            workspace_id=workspace.id,
            workspace_name=workspace.workspace_name,
            was_created=True,
        )

    def sync_profile_context(self, user_id: UUID, workspace_id: UUID, *, force: bool = False) -> None:
        from components.identity.application.providers.workspace_bootstrap_provider import get_workspace_bootstrap_provider
        from infrastructure.persistence.workspaces.models import Workspace
        user = self._get_user(user_id)
        workspace = Workspace.objects.get(id=workspace_id)
        get_workspace_bootstrap_provider().sync_profile_context(user, workspace, force_workspace=force)

    def ensure_follower(self, workspace_id: UUID, user_id: UUID) -> None:
        from components.workspace.application.facades.workspace_facade import ensure_workspace_follower
        from infrastructure.persistence.workspaces.models import Workspace
        user = self._get_user(user_id)
        workspace = Workspace.objects.get(id=workspace_id)
        ensure_workspace_follower(workspace, user)
