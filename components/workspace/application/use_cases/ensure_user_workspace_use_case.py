"""Use case: Ensure a user has a resolvable workspace context.

Called during login/onboarding to either find an existing workspace
or create a personal workspace for the user.

No Django imports — depends only on ports.
"""

from __future__ import annotations

from uuid import UUID

from components.workspace.application.ports.user_onboarding_workspace_port import (
    OnboardingWorkspaceResult,
    UserOnboardingWorkspacePort,
)


class EnsureUserWorkspaceUseCase:
    """Application use case for user-onboarding workspace resolution."""

    def __init__(self, onboarding_port: UserOnboardingWorkspacePort) -> None:
        self._port = onboarding_port

    def execute(self, user_id: UUID, *, create_if_missing: bool = False) -> OnboardingWorkspaceResult | None:
        """Resolve or create a workspace for the user.

        Returns the resolved workspace info, or None if no workspace
        can be found and create_if_missing is False.
        """
        workspace_id = self._port.find_preferred_workspace_id(user_id)
        was_created = False

        if workspace_id is None and create_if_missing:
            result = self._port.create_personal_workspace(user_id)
            if result is None:
                return None
            workspace_id = result.workspace_id
            was_created = result.was_created

        if workspace_id is None:
            return None

        self._port.sync_profile_context(user_id, workspace_id, force=was_created)
        self._port.ensure_follower(workspace_id, user_id)

        return OnboardingWorkspaceResult(
            workspace_id=workspace_id,
            workspace_name="",  # Caller can enrich if needed
            was_created=was_created,
        )
