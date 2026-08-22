"""Use case: change ``Workspace.autonomy_mode`` — the owning-context write (ADR 0035 D8).

``Workspace`` is the workspace context's own model, so this context owns the
write. The agents context reads the mode through a port and never writes it.

**The audit is not optional decoration.** D8 calls a mode change the single
highest-consequence setting in the product and the one an incident review asks
about first — "who widened this, and when?". So the change and its field-change
audit are one owner-side operation, keyed on the workspace instance, exactly as
the AI kill switch beside it does.

**An unknown mode is rejected, not coerced.** Writing an uninterpretable string
would leave the enforcement side parsing it back to UNKNOWN, and a workspace
whose policy reads UNKNOWN has no defined ceiling. Fail the request instead.

No Django imports — depends only on ports + another context's application provider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from components.shared_kernel.domain.errors import NotFoundError, ValidationError
from components.workspace.application.ports.workspace_autonomy_store_port import (
    WorkspaceAutonomyStorePort,
)

logger = logging.getLogger(__name__)

#: The modes an operator may select. EVALUATION and UNKNOWN exist in the enum
#: but are not settings: one is imposed by the eval harness for the duration of
#: a run, the other is the absence of a recorded value.
SELECTABLE_MODES = ("manual", "assist", "autonomous")


@dataclass(frozen=True)
class SetWorkspaceAutonomyModeResult:
    previous: str
    current: str
    changed: bool


class SetWorkspaceAutonomyModeUseCase:
    """Persist a workspace's autonomy mode, with a field-change audit."""

    def __init__(self, store: WorkspaceAutonomyStorePort) -> None:
        self._store = store

    def execute(
        self,
        *,
        workspace_id: str,
        mode: str,
        actor: Any = None,
        reason: str = "",
    ) -> SetWorkspaceAutonomyModeResult:
        normalized = str(mode or "").strip().lower()
        if normalized not in SELECTABLE_MODES:
            raise ValidationError(
                f"'{mode}' is not a selectable autonomy mode. Choose one of: {', '.join(SELECTABLE_MODES)}."
            )

        result = self._store.set_mode(str(workspace_id), mode=normalized)
        if result is None:
            raise NotFoundError(f"Workspace {workspace_id} not found")

        try:
            from components.audit.application.providers.audit_log_provider import (
                get_audit_log_provider,
            )

            get_audit_log_provider().log_field_change(
                instance=result.instance,
                field_name="autonomy_mode",
                previous_value=result.previous,
                new_value=normalized,
                actor=actor,
                reason=reason,
            )
        except Exception:
            # The change itself must not be lost to an audit hiccup, but a
            # silent gap in the trail for THIS field is a governance defect —
            # log loudly so it is findable.
            logger.exception(
                "autonomy_mode audit write failed workspace_id=%s mode=%s actor_id=%s",
                workspace_id,
                normalized,
                getattr(actor, "id", None),
            )

        logger.info(
            "autonomy_mode_changed workspace_id=%s previous=%s current=%s changed=%s actor_id=%s",
            workspace_id,
            result.previous,
            normalized,
            result.changed,
            getattr(actor, "id", None),
        )
        return SetWorkspaceAutonomyModeResult(previous=result.previous, current=normalized, changed=result.changed)
