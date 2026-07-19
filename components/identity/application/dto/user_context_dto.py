"""DTOs for user context queries (onboarding, summary, workspace membership)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OrgOnboardingPayloadDto:
    """Onboarding gate payload used by the frontend to enforce org onboarding."""

    requires_org_onboarding: bool
    org_membership_count: int
    org_access_workspaces: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WorkspaceContextDto:
    """Lightweight workspace context for UI bootstrapping."""

    active_workspace_id: str | None
    active_workspace_kind: str | None
    active_workspace_role: str | None
    active_workspace_is_owner: bool
    active_workspace_is_personal_owner: bool
    has_personal_workspace: bool
    has_org_workspaces: bool
    personal_workspace_ids: list[str] = field(default_factory=list)
    org_workspace_ids: list[str] = field(default_factory=list)
    # ISO 4217 code that drives money formatting on the client until a
    # payment method is connected. Mirrors Workspace.default_currency.
    # ``None`` indicates no active workspace; callers should fall back
    # to the platform default ('USD').
    active_workspace_default_currency: str | None = None
    # AI chat quota snapshot for the active workspace — drives the
    # quota pill in the chat header. Shape:
    # ``{ai_enabled, daily_message_budget, daily_messages_used,
    #    daily_messages_remaining, monthly_token_budget,
    #    monthly_tokens_used, monthly_tokens_remaining}``. -1 in any
    # ``*_remaining`` field means unlimited (budget == 0). Populated
    # by the identity controller via
    # ``build_workspace_ai_quota_snapshot``; ``None`` for users with
    # no active workspace or when the snapshot lookup fails.
    active_workspace_ai_quota: dict | None = None


@dataclass(frozen=True)
class UserSummaryDto:
    """User identity summary data for post-login hydration (no serialized payloads)."""

    user_id: str
    active_workspace_id: str | None
    workspace_context: WorkspaceContextDto
    team_ids: list[str] = field(default_factory=list)
    workspace_ids: list[str] = field(default_factory=list)
