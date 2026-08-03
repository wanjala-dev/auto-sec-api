"""Adapter: is the actor a workspace owner/admin? (ADR 0012 P5 governance gate).

Implements :class:`RemediationGovernancePort` by reading the workspace membership
model — a persistence read of ``infrastructure.persistence.workspaces``, the same
sanctioned "read another context's persistence through my own port" pattern the
``board_finding_facts_repository`` uses (NOT a ``components.workspace.infrastructure``
import, so it never crosses the component-infrastructure boundary).

Authorised iff the actor is the workspace's ``workspace_owner`` OR holds a
membership row with role ``owner``/``admin`` in that workspace. Fail-closed on every
other case (no actor, non-member, plain member, or any lookup error) — a governance
gate must deny when it cannot prove authority.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.remediation.application.ports.remediation_governance_port import (
    RemediationGovernancePort,
)

logger = logging.getLogger(__name__)

_PRIVILEGED_ROLES = ("owner", "admin")


class RemediationGovernanceAdapter(RemediationGovernancePort):
    def can_revoke(self, *, workspace_id: UUID, actor_user_id: str | None) -> bool:
        if not actor_user_id or not str(actor_user_id).strip():
            return False
        try:
            from infrastructure.persistence.workspaces.models import (
                Workspace,
                WorkspaceMembership,
            )

            # Direct workspace ownership is the strongest authority.
            if Workspace.objects.filter(id=workspace_id, workspace_owner_id=actor_user_id).exists():
                return True

            # Otherwise an owner/admin membership row in THIS workspace.
            return WorkspaceMembership.objects.filter(
                workspace_id=workspace_id,
                user_id=actor_user_id,
                role__in=_PRIVILEGED_ROLES,
            ).exists()
        except Exception:
            # Fail-closed backstop: a lookup error must never authorise (deny, loud).
            logger.exception(
                "remediation_governance_errored_failing_closed workspace_id=%s actor_id=%s",
                workspace_id,
                actor_user_id,
            )
            return False
