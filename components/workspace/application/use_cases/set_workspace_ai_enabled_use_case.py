"""Use case: flip ``Workspace.ai_teammate_enabled`` — the owning-context write.

``Workspace`` is the workspace context's own model, so this context owns the
write to its ``ai_teammate_enabled`` field (architecture-manifesto Rule 2 /
architecture-skill C2). The agents context's AI kill switch delegates here
(through :class:`WorkspaceAiTogglePort`) instead of mutating the workspace
itself — keeping the field write on the owning side of the boundary.

The flip and its field-change audit are one owner-side operation: the audit is
*about* a change to a ``Workspace`` field and is keyed on the workspace
instance, so it belongs with the write. The audit goes through the audit
context's application provider (never its infrastructure). Governance policy —
the mandatory typed reason and the kill-switch-status read — stays in the
agents use case that calls this one; here we only require a non-empty reason so
the audit entry always carries one.

No Django imports — depends only on ports + another context's application
provider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from components.shared_kernel.domain.errors import NotFoundError
from components.workspace.application.ports.workspace_ai_toggle_store_port import (
    WorkspaceAiToggleStorePort,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SetWorkspaceAiEnabledResult:
    previous: bool
    changed: bool


class SetWorkspaceAiEnabledUseCase:
    """Persist the AI-teammate flag for a workspace, with a field-change audit."""

    def __init__(self, store: WorkspaceAiToggleStorePort) -> None:
        self._store = store

    def execute(
        self,
        *,
        workspace_id: str,
        enabled: bool,
        actor: Any = None,
        reason: str = "",
    ) -> SetWorkspaceAiEnabledResult:
        result = self._store.set_ai_enabled(str(workspace_id), enabled=bool(enabled))
        if result is None:
            raise NotFoundError(f"Workspace {workspace_id} not found")

        # Audit through the audit context's application provider (never its
        # infrastructure directly). The facade suppresses identical-value writes
        # itself, so a repeat request never fabricates a second "flip".
        try:
            from components.audit.application.providers.audit_log_provider import (
                get_audit_log_provider,
            )

            get_audit_log_provider().log_field_change(
                instance=result.instance,
                field_name="ai_teammate_enabled",
                previous_value=result.previous,
                new_value=bool(enabled),
                actor=actor,
                reason=reason,
            )
        except Exception:
            # The flip itself must not be lost to an audit hiccup, but a silent
            # audit gap is a governance defect — log loudly.
            logger.exception(
                "ai_teammate_enabled audit write failed workspace_id=%s enabled=%s actor_id=%s",
                workspace_id,
                enabled,
                getattr(actor, "id", None),
            )

        return SetWorkspaceAiEnabledResult(previous=result.previous, changed=result.changed)
