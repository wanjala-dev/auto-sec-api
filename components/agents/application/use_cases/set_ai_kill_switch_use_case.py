"""Human-only AI kill switch — flip ``Workspace.ai_teammate_enabled`` with audit.

The actor side of the governance slice (vision §3.4): the workspace AI
toggle stops the scheduled detector fan-out (``iter_enabled_seeds``), the
entitlement gate (``resolve_agent_entitlement`` → ``workspace_ai_disabled``)
and therefore chat, deep runs and async specialist dispatch. This use case
makes the flip first-class: owner/admin-gated at the endpoint, a mandatory
typed reason, and an immutable audit entry (actor + reason + timestamp)
written through the audit context's application provider.

Deliberately NOT an agent tool — an AI that can disable or re-enable its own
containment control defeats the control. The read side lives in
``ai_governance_service.kill_switch_status``.
"""

from __future__ import annotations

import logging
from typing import Any

from components.shared_kernel.domain.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

_MAX_REASON_LENGTH = 500


class SetAiKillSwitchUseCase:
    """Flip the workspace AI kill switch, audited, and return the new status."""

    def execute(
        self,
        *,
        workspace_id: str,
        enabled: bool,
        actor: Any,
        reason: str,
    ) -> dict[str, Any]:
        from infrastructure.persistence.workspaces.models import Workspace

        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("A reason is required to flip the AI kill switch.")
        if len(reason) > _MAX_REASON_LENGTH:
            raise ValidationError(f"Reason must be at most {_MAX_REASON_LENGTH} characters.")
        if not isinstance(enabled, bool):
            raise ValidationError("enabled must be a boolean.")

        queryset = getattr(Workspace, "_base_manager", None) or Workspace.objects
        workspace = queryset.filter(id=str(workspace_id)).first()
        if workspace is None:
            raise NotFoundError(f"Workspace {workspace_id} not found")

        previous = bool(workspace.ai_teammate_enabled)
        if previous != enabled:
            workspace.ai_teammate_enabled = enabled
            workspace.save(update_fields=["ai_teammate_enabled"])

        # Audit through the audit context's application provider (never its
        # infrastructure directly). Written even for a no-op request? No —
        # the audit facade suppresses identical-value writes itself, so a
        # repeat click never fabricates a second "flip" in the record.
        try:
            from components.audit.application.providers.audit_log_provider import (
                get_audit_log_provider,
            )

            get_audit_log_provider().log_field_change(
                instance=workspace,
                field_name="ai_teammate_enabled",
                previous_value=previous,
                new_value=enabled,
                actor=actor,
                reason=reason,
            )
        except Exception:
            # The flip itself must not be lost to an audit hiccup, but a
            # silent audit gap is a governance defect — log loudly.
            logger.exception(
                "ai_kill_switch audit write failed workspace_id=%s enabled=%s actor_id=%s",
                workspace_id,
                enabled,
                getattr(actor, "id", None),
            )

        logger.info(
            "ai_kill_switch flipped workspace_id=%s enabled=%s previous=%s actor_id=%s",
            workspace_id,
            enabled,
            previous,
            getattr(actor, "id", None),
        )

        from components.agents.application.services import ai_governance_service

        return ai_governance_service.kill_switch_status(str(workspace_id))
