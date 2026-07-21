"""Infrastructure adapter: monthly AI-run quota.

Implements :class:`AiRunQuotaPort`. The run tally is stored on the existing
per-workspace ``WorkspaceAIUsage`` row (``monthly_runs_used``, its own monthly
window) — the SAME system that tracks chat messages/tokens — so there is one
workspace AI-usage record, one reset path, and one ``me/summary`` snapshot
rather than a parallel counter. Runs are read/recorded through the
``WorkspaceAIConfigPort`` (which owns ``WorkspaceAIUsage`` + its window logic);
this adapter only adds the tier-driven *cap*.

Runs (execute + deep_run) are the monetization lever — chat is never recorded
here (it goes through the message/token guardrail instead). The cap is
data-driven: resolved from the workspace's tier limits through
:class:`EntitlementsResolver` (plan limits ← workspace overrides), keyed on
``EntitlementKey.MAX_AI_RUNS_PER_MONTH``. ``None`` = unlimited.
"""
from __future__ import annotations

import logging

from components.agents.application.ports.ai_run_quota_port import (
    AiRunQuotaPort,
    AiRunQuotaStatus,
)
from components.agents.application.ports.workspace_ai_config_port import (
    WorkspaceAIConfigPort,
)
from components.subscription.domain.entitlements import (
    EntitlementKey,
    EntitlementsResolver,
)

logger = logging.getLogger(__name__)


class AiRunQuotaAdapter(AiRunQuotaPort):
    """Reads/records the monthly AI-run tally and resolves the tier cap."""

    def __init__(self, ai_config_port: WorkspaceAIConfigPort | None = None) -> None:
        if ai_config_port is None:
            from components.agents.application.providers.workspace_ai_config_provider import (
                WorkspaceAIConfigProvider,
            )

            ai_config_port = WorkspaceAIConfigProvider().get_port()
        self._ai_config = ai_config_port

    def check_for_workspace(self, workspace_id: str | None) -> AiRunQuotaStatus:
        if not workspace_id:
            # No tier context ⇒ can't gate. Fail open.
            return AiRunQuotaStatus(allowed=True, used=0, limit=None, workspace_id=None)

        limit = self._resolve_monthly_limit(workspace_id)
        used = self._ai_config.get_workspace_runs_this_month(str(workspace_id))
        return AiRunQuotaStatus(
            allowed=limit is None or used < limit,
            used=used,
            limit=limit,
            workspace_id=str(workspace_id),
        )

    def check_for_agent(self, agent_id: str | None) -> AiRunQuotaStatus:
        return self.check_for_workspace(self._resolve_workspace_for_agent(agent_id))

    def record_run(self, workspace_id: str | None) -> None:
        if not workspace_id:
            return
        self._ai_config.record_workspace_run(str(workspace_id))

    # ── internals ────────────────────────────────────────────────────

    def _resolve_monthly_limit(self, workspace_id: str) -> int | None:
        """Resolve the workspace's monthly AI-run cap, or ``None`` (unlimited)."""
        from infrastructure.persistence.workspaces.models import Workspace

        row = (
            Workspace.objects.filter(id=workspace_id)
            .values_list("plan__limits", "entitlement_overrides")
            .first()
        )
        if not row:
            return None
        plan_limits, workspace_overrides = row
        entitlements = EntitlementsResolver.resolve(
            plan_limits=plan_limits or {},
            workspace_overrides=workspace_overrides or {},
        )
        return entitlements.limit_for(EntitlementKey.MAX_AI_RUNS_PER_MONTH)

    @staticmethod
    def _resolve_workspace_for_agent(agent_id: str | None) -> str | None:
        if not agent_id:
            return None
        from infrastructure.persistence.ai.agents.models import Agent

        workspace_id = (
            Agent.objects.filter(pk=agent_id)
            .values_list("workspace_id", flat=True)
            .first()
        )
        return str(workspace_id) if workspace_id else None
