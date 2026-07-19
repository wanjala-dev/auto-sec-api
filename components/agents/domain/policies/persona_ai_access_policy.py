"""Persona-based AI access policy — gates what each persona can do with AI.

Evaluates a user's persona role against the workspace AI config to determine:
- Whether they can use a specific AI feature
- Which agent types they can access
- How many messages/tokens they're allowed
- What information depth the AI should provide

Pure domain policy — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from components.agents.domain.value_objects.workspace_ai_config import (
    WorkspaceAIConfig,
)


class AIFeature(StrEnum):
    """AI features that can be gated per persona."""

    WORKSPACE_CHAT = "workspace_chat"
    PDF_CHAT = "pdf_chat"
    DEEP_RUNS = "deep_runs"
    VIEW_AI_ACTIONS = "view_ai_actions"


class AccessDecision(StrEnum):
    """Result of an access check."""

    ALLOWED = "allowed"
    DENIED_AI_DISABLED = "denied_ai_disabled"
    DENIED_FEATURE_BLOCKED = "denied_feature_blocked"
    DENIED_AGENT_BLOCKED = "denied_agent_blocked"
    # Per-user / per-persona daily message cap (legacy — kept for the
    # PersonaAILimits "max_messages_per_day" path).
    DENIED_DAILY_LIMIT = "denied_daily_limit"
    DENIED_TOKEN_LIMIT = "denied_token_limit"
    # Workspace-level caps (the GTM cost-gate added in PR #5). These
    # surface as HTTP 429 so the frontend can render a quota-exceeded
    # banner with the reset window; the per-persona DAILY_LIMIT above
    # surfaces as 403 because it's a configuration/role decision the
    # workspace owner can change, not a usage cap.
    DENIED_WORKSPACE_DAILY_MESSAGE_LIMIT = "denied_workspace_daily_message_limit"
    DENIED_WORKSPACE_MONTHLY_TOKEN_LIMIT = "denied_workspace_monthly_token_limit"


@dataclass(frozen=True)
class AIAccessCheckResult:
    """Result of evaluating persona access to an AI feature.

    Carries both per-persona and per-workspace remaining-budget values
    so the caller can surface them on the response (HTTP 429 body, the
    chat-window quota pill, etc.). -1 means "unlimited / not applicable".
    """

    decision: AccessDecision
    reason: str
    max_tokens: int = 0
    # Per-persona / per-user remaining messages today. -1 = unlimited.
    remaining_messages: int = -1
    # Workspace-level remaining (shared across the org). -1 = unlimited.
    workspace_daily_remaining_messages: int = -1
    workspace_monthly_remaining_tokens: int = -1

    @property
    def is_allowed(self) -> bool:
        return self.decision == AccessDecision.ALLOWED

    @property
    def is_workspace_quota_exceeded(self) -> bool:
        """True for the two workspace-level caps that map to HTTP 429."""
        return self.decision in (
            AccessDecision.DENIED_WORKSPACE_DAILY_MESSAGE_LIMIT,
            AccessDecision.DENIED_WORKSPACE_MONTHLY_TOKEN_LIMIT,
        )


class PersonaAIAccessPolicy:
    """Evaluate whether a persona role can use a specific AI feature.

    The workspace owner configures limits via WorkspaceAIConfig.
    This policy applies those limits at request time.
    """

    def check_feature_access(
        self,
        *,
        persona_role: str,
        feature: AIFeature,
        config: WorkspaceAIConfig,
        messages_used_today: int = 0,
        workspace_messages_today: int = 0,
        workspace_tokens_this_month: int = 0,
    ) -> AIAccessCheckResult:
        """Check if the persona can use this AI feature.

        Checks are ordered cheapest-first and most-blocking-first:

        1. AI disabled at workspace level (master switch).
        2. Per-persona feature toggle (workspace owner's persona config).
        3. Per-persona daily message cap (the seat-level limit).
        4. **Workspace daily message cap** (shared org pool — GTM gate).
        5. **Workspace monthly token ceiling** (ops kill-switch — GTM gate).

        Steps 4 and 5 are the GTM cost gates added in PR #5. They map
        to HTTP 429 (rate limited / quota exceeded). The earlier
        per-persona check maps to 403 because the workspace owner can
        change it — it's role-level configuration, not a usage cap.
        """

        # 1. Master toggle
        if not config.ai_enabled:
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_AI_DISABLED,
                reason="AI is disabled for this workspace.",
            )

        limits = config.get_limits_for_persona(persona_role)

        # 2. Feature-level check
        feature_map = {
            AIFeature.WORKSPACE_CHAT: limits.can_use_chat,
            AIFeature.PDF_CHAT: limits.can_use_pdf_chat,
            AIFeature.DEEP_RUNS: limits.can_use_deep_runs,
            AIFeature.VIEW_AI_ACTIONS: limits.can_view_ai_actions,
        }
        if not feature_map.get(feature, False):
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_FEATURE_BLOCKED,
                reason=f"Your role ({persona_role}) does not have access to {feature.value}.",
            )

        # 3. Per-persona daily message limit
        if not limits.is_unlimited and messages_used_today >= limits.max_messages_per_day:
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_DAILY_LIMIT,
                reason=(
                    f"Daily message limit reached ({limits.max_messages_per_day} messages). "
                    "Contact your workspace admin to increase your limit."
                ),
                remaining_messages=0,
            )

        # Compute workspace-level remaining now so we can return them
        # even on the GTM-cap branches below.
        ws_daily_budget = config.workspace_daily_message_budget
        ws_daily_unlimited = ws_daily_budget == 0
        ws_daily_remaining = (
            -1 if ws_daily_unlimited else max(0, ws_daily_budget - workspace_messages_today)
        )

        ws_monthly_budget = config.monthly_token_budget
        ws_monthly_unlimited = ws_monthly_budget == 0
        ws_monthly_remaining = (
            -1
            if ws_monthly_unlimited
            else max(0, ws_monthly_budget - workspace_tokens_this_month)
        )

        # 4. Workspace daily message cap (GTM gate → 429)
        if not ws_daily_unlimited and workspace_messages_today >= ws_daily_budget:
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_WORKSPACE_DAILY_MESSAGE_LIMIT,
                reason=(
                    f"Workspace has hit its daily AI chat limit "
                    f"({ws_daily_budget} messages). Resets at midnight UTC. "
                    "Workspace owners can raise this limit in AI settings."
                ),
                workspace_daily_remaining_messages=0,
                workspace_monthly_remaining_tokens=ws_monthly_remaining,
            )

        # 5. Workspace monthly token ceiling (GTM gate → 429)
        if not ws_monthly_unlimited and workspace_tokens_this_month >= ws_monthly_budget:
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_WORKSPACE_MONTHLY_TOKEN_LIMIT,
                reason=(
                    f"Workspace has hit its monthly AI token ceiling "
                    f"({ws_monthly_budget:,} tokens). Resets on the 1st of next month. "
                    "Contact support to discuss raising your plan."
                ),
                workspace_daily_remaining_messages=ws_daily_remaining,
                workspace_monthly_remaining_tokens=0,
            )

        remaining = -1 if limits.is_unlimited else (limits.max_messages_per_day - messages_used_today)

        return AIAccessCheckResult(
            decision=AccessDecision.ALLOWED,
            reason="Access granted.",
            max_tokens=limits.max_tokens_per_message,
            remaining_messages=remaining,
            workspace_daily_remaining_messages=ws_daily_remaining,
            workspace_monthly_remaining_tokens=ws_monthly_remaining,
        )

    def check_agent_access(
        self,
        *,
        persona_role: str,
        agent_type: str,
        config: WorkspaceAIConfig,
    ) -> AIAccessCheckResult:
        """Check if the persona can use a specific agent type."""

        if not config.ai_enabled:
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_AI_DISABLED,
                reason="AI is disabled for this workspace.",
            )

        limits = config.get_limits_for_persona(persona_role)

        # Check blocked list
        if agent_type in limits.blocked_agent_types:
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_AGENT_BLOCKED,
                reason=f"Your role ({persona_role}) cannot use the {agent_type} agent.",
            )

        # Check allowed list (empty = all allowed)
        if limits.allowed_agent_types and agent_type not in limits.allowed_agent_types:
            return AIAccessCheckResult(
                decision=AccessDecision.DENIED_AGENT_BLOCKED,
                reason=f"Your role ({persona_role}) does not have access to the {agent_type} agent.",
            )

        return AIAccessCheckResult(
            decision=AccessDecision.ALLOWED,
            reason="Access granted.",
            max_tokens=limits.max_tokens_per_message,
        )

    def get_effective_max_tokens(
        self,
        *,
        persona_role: str,
        config: WorkspaceAIConfig,
    ) -> int:
        """Return the effective max tokens for this persona's responses."""
        limits = config.get_limits_for_persona(persona_role)
        return min(limits.max_tokens_per_message, config.max_tokens)
