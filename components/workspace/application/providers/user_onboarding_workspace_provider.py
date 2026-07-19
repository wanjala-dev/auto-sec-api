"""Composition root for user-onboarding workspace bootstrap.

Wires the concrete ORM adapter to the EnsureUserWorkspaceUseCase.
"""

from __future__ import annotations

from components.workspace.application.use_cases.ensure_user_workspace_use_case import (
    EnsureUserWorkspaceUseCase,
)
from components.workspace.infrastructure.repositories.user_onboarding_workspace_repository import (
    UserOnboardingWorkspaceRepository,
)


class UserOnboardingWorkspaceProvider:
    """Builds the fully-wired use case for user onboarding workspace resolution."""

    @staticmethod
    def build_ensure_workspace_use_case() -> EnsureUserWorkspaceUseCase:
        return EnsureUserWorkspaceUseCase(
            onboarding_port=UserOnboardingWorkspaceRepository(),
        )
