"""Adapter: ``InviteTeamEnrollmentPort`` → the canonical team-enrollment machinery.

Resolves the user/workspace/team rows and delegates to
``OrmTeamMembershipRepository.enroll_user_in_team`` (via the provider) — the ONE
enrollment implementation (team members M2M + workspace follower/membership +
``TeamMembership`` row + profile active-context update). Reuses, never re-rolls,
that choreography (dry-reuse).

Missing rows (a team deleted between invite and accept) are a logged no-op —
the accept flow's WorkspaceMembership write must still land. Anything else
propagates: the silent ``except Exception: pass`` that hid #60 for months is
exactly what this adapter must never reintroduce.
"""

from __future__ import annotations

import logging

from components.team.application.ports.invite_team_enrollment_port import (
    InviteTeamEnrollmentPort,
)

logger = logging.getLogger(__name__)


class InviteTeamEnrollmentAdapter(InviteTeamEnrollmentPort):
    def enroll(
        self,
        *,
        user_id: str,
        workspace_id: str,
        team_id: str,
        mark_contributor: bool,
    ) -> bool:
        from components.team.application.providers.team_membership_provider import (
            TeamMembershipProvider,
        )
        from infrastructure.persistence.team.models import Team
        from infrastructure.persistence.users.models import CustomUser
        from infrastructure.persistence.workspaces.models import Workspace

        user = CustomUser.objects.filter(id=user_id).first()
        workspace = Workspace.objects.filter(id=workspace_id).first()
        team = Team.objects.filter(id=team_id, workspace_id=workspace_id).first()
        if user is None or workspace is None or team is None:
            logger.warning(
                "invite_team_enrollment_target_missing user_id=%s workspace_id=%s team_id=%s "
                "user_found=%s workspace_found=%s team_found=%s",
                user_id,
                workspace_id,
                team_id,
                user is not None,
                workspace is not None,
                team is not None,
            )
            return False

        TeamMembershipProvider().build_store().enroll_user_in_team(
            user,
            workspace,
            team,
            mark_contributor=mark_contributor,
            # The invitee's profile should land in the invited team's context —
            # the original (pre-#60) inline enrollment passed the same flag.
            update_active_context=True,
        )
        logger.info(
            "invite_team_enrollment_completed user_id=%s workspace_id=%s team_id=%s",
            user_id,
            workspace_id,
            team_id,
        )
        return True
