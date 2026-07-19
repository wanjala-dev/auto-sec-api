"""Compose the workspace AI quota snapshot surfaced on me/summary.

Pure application-layer function that takes a ``WorkspaceAIConfigPort``
and returns the dict the frontend reads to render the chat-header
quota pill. Lives in the agents context because the budget definitions
(daily message cap, monthly token cap) are AI-domain knowledge.

Cross-context callers (e.g. ``components.identity.api.controller``)
import this function and inject the adapter at the controller boundary,
keeping the policy logic on this side of the bounded-context line.
"""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.ai_run_quota_port import AiRunQuotaPort
from components.agents.application.ports.workspace_ai_config_port import (
    WorkspaceAIConfigPort,
)


def build_workspace_ai_quota_snapshot(
    workspace_id: str,
    *,
    ai_config_port: WorkspaceAIConfigPort,
    ai_run_quota_port: AiRunQuotaPort | None = None,
) -> dict[str, Any]:
    """Compose the AI quota snapshot for one workspace.

    Returns a dict matching the shape documented on
    ``WorkspaceContextDto.active_workspace_ai_quota``. A budget of 0
    means "unlimited" and surfaces as ``*_remaining == -1`` so the
    frontend can render "unlimited" rather than "0 remaining".

    Failure-safe at the caller boundary: this function will propagate
    exceptions raised by the port (e.g. DB outage), but the caller
    should wrap the call in try/except and return ``None`` so a
    snapshot failure never breaks the me/summary endpoint.
    """
    config = ai_config_port.load(workspace_id)
    daily_used = ai_config_port.get_workspace_messages_today(workspace_id)
    monthly_used = ai_config_port.get_workspace_tokens_this_month(workspace_id)

    daily_budget = config.workspace_daily_message_budget
    monthly_budget = config.monthly_token_budget

    # Metered-AI runs (execute + deep_run) — the tier monetization lever.
    # Same 0==unlimited / -1==remaining convention as the guardrail budgets.
    # ``limit is None`` (Premium / no plan) maps to budget 0 (unlimited).
    runs_used = 0
    runs_budget = 0
    if ai_run_quota_port is not None:
        runs = ai_run_quota_port.check_for_workspace(workspace_id)
        runs_used = runs.used
        runs_budget = 0 if runs.limit is None else runs.limit

    return {
        "ai_enabled": config.ai_enabled,
        "daily_message_budget": daily_budget,
        "daily_messages_used": daily_used,
        "daily_messages_remaining": (
            -1 if daily_budget == 0 else max(0, daily_budget - daily_used)
        ),
        "monthly_token_budget": monthly_budget,
        "monthly_tokens_used": monthly_used,
        "monthly_tokens_remaining": (
            -1 if monthly_budget == 0 else max(0, monthly_budget - monthly_used)
        ),
        "monthly_run_budget": runs_budget,
        "monthly_runs_used": runs_used,
        "monthly_runs_remaining": (
            -1 if runs_budget == 0 else max(0, runs_budget - runs_used)
        ),
    }
