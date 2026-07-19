"""Port: establish an authenticated user's relationship with a workspace.

Backs onboarding's "support an existing organization" flow once the user
is already logged in. The four relationships have different persistence
shapes (follow = M2M, sponsor = active viewer membership, volunteer /
contribute = pending membership + owner-approval request) — this port
exposes them as granular primitives so the use case can hold the routing
policy and the adapter holds the ORM wiring.

No Django imports — standard library only.
"""

from __future__ import annotations

import abc
import enum
from dataclasses import dataclass


class TeamJoinOutcome(enum.Enum):
    """Result of requesting a team (volunteer/contributor) join."""

    REQUESTED = "requested"          # pending membership + request created
    ALREADY_PENDING = "already_pending"  # a request was already open
    NOT_ALLOWED = "not_allowed"      # workspace isn't requestable (e.g. public)


@dataclass(frozen=True)
class TeamJoinResult:
    outcome: TeamJoinOutcome
    detail: str = ""


@dataclass(frozen=True)
class RelationshipOutcome:
    """What the controller returns to the FE so it knows where to land."""

    relationship: str
    workspace_id: str
    redirect: str  # "dashboard" | "profile"
    persona: str | None = None
    status: str | None = None


class WorkspaceRelationshipPort(abc.ABC):
    """Secondary port for self-service workspace relationship persistence."""

    @abc.abstractmethod
    def workspace_exists(self, *, workspace_id: str) -> bool: ...

    @abc.abstractmethod
    def add_follower(self, *, workspace_id: str, user_id: str) -> None:
        """Add the user to the workspace followers (no membership)."""

    @abc.abstractmethod
    def active_membership_persona(
        self, *, workspace_id: str, user_id: str
    ) -> str | None:
        """Persona of the user's ACTIVE membership, or None if not a member."""

    @abc.abstractmethod
    def upsert_sponsor_membership(
        self, *, workspace_id: str, user_id: str
    ) -> None:
        """Idempotently ensure an ACTIVE persona=sponsor, role=viewer membership.

        Never downgrades a richer existing membership (owner/admin/contributor).
        """

    @abc.abstractmethod
    def request_team_join(
        self, *, workspace_id: str, user_id: str, persona: str
    ) -> TeamJoinResult:
        """Raise an owner-approval request and create the paired PENDING membership.

        Atomic. ``persona`` is "contributor" or "volunteer".
        """
