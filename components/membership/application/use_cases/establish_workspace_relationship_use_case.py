"""Use case: establish an authenticated user's relationship with a workspace.

Holds the routing policy for onboarding's "support an existing
organization" step. Persistence lives behind ``WorkspaceRelationshipPort``;
this use case only decides which primitive to call and where the FE should
land.

No Django / DRF imports — application layer purity.
"""

from __future__ import annotations

from dataclasses import dataclass

from components.membership.application.ports.workspace_relationship_port import (
    RelationshipOutcome,
    TeamJoinOutcome,
    WorkspaceRelationshipPort,
)
from components.shared_kernel.domain.errors import (
    NotFoundError,
    ValidationError,
)

# Relationship → membership persona for the approval-gated team joins.
_TEAM_PERSONA = {
    "volunteer": "volunteer",
    "contribute": "contributor",
    "contributor": "contributor",
}
_VALID_RELATIONSHIPS = {"follow", "sponsor", *_TEAM_PERSONA.keys()}


@dataclass(frozen=True)
class EstablishWorkspaceRelationshipCommand:
    workspace_id: str
    user_id: str
    relationship: str


@dataclass
class EstablishWorkspaceRelationshipUseCase:
    port: WorkspaceRelationshipPort

    def execute(
        self, command: EstablishWorkspaceRelationshipCommand
    ) -> RelationshipOutcome:
        relationship = (command.relationship or "").strip().lower()
        if relationship not in _VALID_RELATIONSHIPS:
            raise ValidationError(
                "relationship must be follow, sponsor, volunteer, or contribute."
            )
        if not command.workspace_id:
            raise ValidationError("workspace_id is required.")
        if not self.port.workspace_exists(workspace_id=command.workspace_id):
            raise NotFoundError("Workspace not found.")

        if relationship == "follow":
            # Lightweight follow — no membership/persona. FE → org profile.
            self.port.add_follower(
                workspace_id=command.workspace_id, user_id=command.user_id
            )
            return RelationshipOutcome(
                relationship="follow",
                workspace_id=command.workspace_id,
                redirect="profile",
            )

        if relationship == "sponsor":
            self.port.upsert_sponsor_membership(
                workspace_id=command.workspace_id, user_id=command.user_id
            )
            return RelationshipOutcome(
                relationship="sponsor",
                workspace_id=command.workspace_id,
                redirect="dashboard",
                persona="sponsor",
                status="active",
            )

        # Volunteer / contribute — these enter the org's INTERNAL workspace, so
        # they stay owner-approval-gated.
        persona = _TEAM_PERSONA[relationship]

        existing_persona = self.port.active_membership_persona(
            workspace_id=command.workspace_id, user_id=command.user_id
        )
        if existing_persona:
            # Already an active member — nothing to request, just land them.
            return RelationshipOutcome(
                relationship=relationship,
                workspace_id=command.workspace_id,
                redirect="dashboard",
                persona=existing_persona,
                status="active",
            )

        result = self.port.request_team_join(
            workspace_id=command.workspace_id,
            user_id=command.user_id,
            persona=persona,
        )
        if result.outcome == TeamJoinOutcome.NOT_ALLOWED:
            raise ValidationError(
                result.detail or "This workspace is not open to join requests."
            )

        # REQUESTED or ALREADY_PENDING — either way they land on the persona
        # dashboard behind the "pending approval" lock until the owner approves.
        return RelationshipOutcome(
            relationship=relationship,
            workspace_id=command.workspace_id,
            redirect="dashboard",
            persona=persona,
            status="pending",
        )
