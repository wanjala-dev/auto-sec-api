"""Application-layer queries for user context (onboarding, summary).

These replace the inline ORM helper functions that were in users_controller.py.
"""
from __future__ import annotations

import logging
from typing import Any

from components.identity.application.dto.user_context_dto import (
    OrgOnboardingPayloadDto,
    UserSummaryDto,
    WorkspaceContextDto,
)
from components.identity.application.ports.user_context_query_port import UserContextQueryPort

logger = logging.getLogger(__name__)


class BuildOrgOnboardingPayloadQuery:
    """Build the org-onboarding gate payload for a user.

    Replaces _build_org_onboarding_payload() from users_controller.py.
    """

    def __init__(self, user_context: UserContextQueryPort):
        self._ctx = user_context

    def execute(
        self,
        *,
        user_id: Any | None,
        include_workspace_ids: bool = True,
    ) -> OrgOnboardingPayloadDto:
        if not user_id:
            return OrgOnboardingPayloadDto(
                requires_org_onboarding=True,
                org_membership_count=0,
                org_access_workspaces=[],
            )

        if include_workspace_ids:
            workspace_ids = self._ctx.get_accessible_workspace_ids(user_id=user_id)
            count = len(workspace_ids)
        else:
            workspace_ids = []
            count = self._ctx.get_org_membership_count(user_id=user_id)

        if self._ctx.is_staff_or_superuser(user_id=user_id):
            return OrgOnboardingPayloadDto(
                requires_org_onboarding=False,
                org_membership_count=count,
                org_access_workspaces=workspace_ids,
            )

        return OrgOnboardingPayloadDto(
            requires_org_onboarding=count == 0,
            org_membership_count=count,
            org_access_workspaces=workspace_ids,
        )


class BuildUserContextQuery:
    """Build lightweight workspace context for post-login hydration.

    Replaces _build_user_summary_payload() workspace logic from users_controller.py.
    """

    def __init__(self, user_context: UserContextQueryPort):
        self._ctx = user_context

    def execute(self, *, user_id: Any) -> UserSummaryDto:
        workspace_ids = self._ctx.get_accessible_workspace_ids(user_id=user_id)
        active_workspace_id = self._ctx.get_active_workspace_id(user_id=user_id)
        team_ids = self._ctx.get_active_team_ids(user_id=user_id)

        # The active workspace MUST be one the user is a member of (owner / membership /
        # team). `get_accessible_workspace_ids` excludes followed-only orgs, so a persisted
        # active_workspace_id that isn't in that set points at an org the user merely follows
        # (or has lost access to). Reporting it as active makes the client land there and 403
        # on every membership-gated call. Fall back to a real membership instead of trusting
        # the stale pointer.
        if active_workspace_id and active_workspace_id not in workspace_ids:
            fallback = workspace_ids[0] if workspace_ids else None
            logger.warning(
                "active_workspace_not_member user_id=%s stale_active_workspace_id=%s "
                "fallback_workspace_id=%s",
                user_id,
                active_workspace_id,
                fallback,
            )
            active_workspace_id = fallback

        # Classify each workspace
        personal_ids: list[str] = []
        org_ids: list[str] = []
        for ws_id in workspace_ids:
            kind = self._ctx.infer_workspace_kind(workspace_id=ws_id)
            if kind == "personal":
                personal_ids.append(ws_id)
            else:
                org_ids.append(ws_id)

        active_ws_kind = (
            self._ctx.infer_workspace_kind(workspace_id=active_workspace_id)
            if active_workspace_id
            else None
        )
        active_ws_role = (
            self._ctx.infer_workspace_role(user_id=user_id, workspace_id=active_workspace_id)
            if active_workspace_id
            else None
        )
        active_ws_is_owner = (
            self._ctx.is_workspace_owner(user_id=user_id, workspace_id=active_workspace_id)
            if active_workspace_id
            else False
        )

        active_ws_currency = (
            self._ctx.get_workspace_default_currency(
                workspace_id=active_workspace_id
            )
            if active_workspace_id
            else None
        )

        workspace_context = WorkspaceContextDto(
            active_workspace_id=active_workspace_id,
            active_workspace_kind=active_ws_kind,
            active_workspace_role=active_ws_role,
            active_workspace_is_owner=active_ws_is_owner,
            active_workspace_is_personal_owner=active_ws_is_owner and active_ws_kind == "personal",
            has_personal_workspace=bool(personal_ids),
            has_org_workspaces=bool(org_ids),
            personal_workspace_ids=personal_ids,
            org_workspace_ids=org_ids,
            active_workspace_default_currency=active_ws_currency,
        )

        return UserSummaryDto(
            user_id=str(user_id),
            active_workspace_id=active_workspace_id,
            workspace_context=workspace_context,
            team_ids=team_ids,
            workspace_ids=workspace_ids,
        )
