"""SEE-202 — emergency AI kill switch.

A containment control: one flag flip halts AI execution across the platform (or
one workspace) without a deploy. Distinct from the per-workspace ``ai_enabled``
setting, which is a normal product toggle owned by the workspace owner — this is
an *operator* break-glass for "AI is misbehaving right now, stop it".

Backed by ``feature.ai_kill_switch`` (default off everywhere). An operator trips
it with a global ``FeatureFlagRule`` to halt all AI, or a workspace-scoped rule
to halt one workspace; ``is_feature_enabled`` resolves both via the standard
user → workspace → global order.

Checked at every AI execution entry point — the unified chat use case, the
deep-run/execute service methods, and the autonomous detector cycle — so a trip
stops new runs on the next request; in-flight runs finish their current node and
stop at the next entry.

Fail-open by design: a flag-system error does NOT halt AI. A kill switch that
self-engages whenever the flag store hiccups would be its own outage — it must
engage only when an operator has explicitly, readably tripped it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

KILL_SWITCH_FLAG = "feature.ai_kill_switch"


def is_ai_killed(workspace_id, *, user=None) -> bool:
    """Return True when AI is emergency-halted for *workspace_id*."""
    if not workspace_id:
        return False
    try:
        # Via the shared_platform application provider, not the infra service
        # directly — keeps this application-layer policy free of a cross-context
        # infrastructure import (see tests/architecture).
        from components.shared_platform.application.providers.feature_flags_provider import (
            get_feature_flags_provider,
        )

        return get_feature_flags_provider().is_feature_enabled(
            KILL_SWITCH_FLAG, user=user, workspace_id=str(workspace_id)
        )
    except Exception:
        logger.warning(
            "ai_kill_switch check failed workspace_id=%s; treating AI as available",
            workspace_id,
            exc_info=True,
        )
        return False
