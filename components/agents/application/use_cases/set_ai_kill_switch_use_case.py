"""Human-only AI kill switch — flip ``Workspace.ai_teammate_enabled`` with audit.

The actor side of the governance slice (vision §3.4): the workspace AI
toggle stops the scheduled detector fan-out (``iter_enabled_seeds``), the
entitlement gate (``resolve_agent_entitlement`` → ``workspace_ai_disabled``)
and therefore chat, deep runs and async specialist dispatch. This use case
makes the flip first-class: owner/admin-gated at the endpoint, a mandatory
typed reason, and an immutable audit entry (actor + reason + timestamp).

``Workspace`` is the *workspace* context's data, so agents does not write it
here (architecture-manifesto Rule 2 / architecture-skill C2 — a component never
changes data it does not own). The flip + its field-change audit are delegated
through :class:`WorkspaceAiTogglePort` to the workspace context, which owns the
write. This use case keeps the governance policy — the mandatory reason, the
boolean guard, and the kill-switch-status read the endpoint returns.

Deliberately NOT an agent tool — an AI that can disable or re-enable its own
containment control defeats the control. The read side lives in
``ai_governance_service.kill_switch_status``.
"""

from __future__ import annotations

import logging
from typing import Any

from components.agents.application.ports.workspace_ai_toggle_port import WorkspaceAiTogglePort
from components.shared_kernel.domain.errors import ValidationError

logger = logging.getLogger(__name__)

_MAX_REASON_LENGTH = 500


class SetAiKillSwitchUseCase:
    """Flip the workspace AI kill switch, audited, and return the new status."""

    def __init__(self, workspace_ai_toggle: WorkspaceAiTogglePort) -> None:
        self._workspace_ai_toggle = workspace_ai_toggle

    def execute(
        self,
        *,
        workspace_id: str,
        enabled: bool,
        actor: Any,
        reason: str,
    ) -> dict[str, Any]:
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("A reason is required to flip the AI kill switch.")
        if len(reason) > _MAX_REASON_LENGTH:
            raise ValidationError(f"Reason must be at most {_MAX_REASON_LENGTH} characters.")
        if not isinstance(enabled, bool):
            raise ValidationError("enabled must be a boolean.")

        # Delegate the flip + its field-change audit to the owning (workspace)
        # context. Raises NotFoundError when the workspace does not exist. The
        # audit facade suppresses identical-value writes itself, so a repeat
        # click never fabricates a second "flip" in the record.
        outcome = self._workspace_ai_toggle.set_ai_enabled(
            workspace_id=str(workspace_id),
            enabled=enabled,
            actor=actor,
            reason=reason,
        )

        logger.info(
            "ai_kill_switch flipped workspace_id=%s enabled=%s previous=%s actor_id=%s",
            workspace_id,
            enabled,
            outcome.previous,
            getattr(actor, "id", None),
        )

        from components.agents.application.services import ai_governance_service

        return ai_governance_service.kill_switch_status(str(workspace_id))
