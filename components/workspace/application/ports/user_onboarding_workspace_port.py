"""Port for user-onboarding workspace resolution and creation.

This port handles the lightweight bootstrap flow triggered on user login
(resolve or create a personal workspace). It is separate from the management
command seed bootstrap which uses WorkspaceBootstrapPort.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class OnboardingWorkspaceResult:
    """Value object returned after onboarding workspace resolution."""

    workspace_id: UUID
    workspace_name: str
    was_created: bool


class UserOnboardingWorkspacePort(ABC):
    """Secondary/driven port for user-onboarding workspace operations."""

    @abstractmethod
    def should_bootstrap(self, user_id: UUID) -> bool:
        """Return True when the user's onboarding state allows auto-bootstrap."""
        ...

    @abstractmethod
    def find_preferred_workspace_id(self, user_id: UUID) -> UUID | None:
        """Return the user's preferred workspace id, or None."""
        ...

    @abstractmethod
    def create_personal_workspace(self, user_id: UUID) -> OnboardingWorkspaceResult | None:
        """Create a default personal workspace for the user."""
        ...

    @abstractmethod
    def sync_profile_context(self, user_id: UUID, workspace_id: UUID, *, force: bool = False) -> None:
        """Update the user's active workspace/team in their profile."""
        ...

    @abstractmethod
    def ensure_follower(self, workspace_id: UUID, user_id: UUID) -> None:
        """Ensure the user follows the given workspace."""
        ...
