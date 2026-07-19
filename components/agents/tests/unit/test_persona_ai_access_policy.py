"""Unit tests for PersonaAIAccessPolicy."""

from components.agents.domain.policies.persona_ai_access_policy import (
    AIFeature,
    AccessDecision,
    PersonaAIAccessPolicy,
)
from components.agents.domain.value_objects.workspace_ai_config import (
    PersonaAILimits,
    WorkspaceAIConfig,
)


class TestPersonaAIAccessPolicy:
    def setup_method(self):
        self.policy = PersonaAIAccessPolicy()

    def test_ai_disabled_blocks_all(self):
        config = WorkspaceAIConfig(ai_enabled=False)
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
        )
        assert not result.is_allowed
        assert result.decision == AccessDecision.DENIED_AI_DISABLED

    def test_owner_has_full_access(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
        )
        assert result.is_allowed

    def test_owner_can_use_deep_runs(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.DEEP_RUNS,
            config=config,
        )
        assert result.is_allowed

    def test_sponsor_blocked_from_deep_runs(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_feature_access(
            persona_role="sponsor",
            feature=AIFeature.DEEP_RUNS,
            config=config,
        )
        assert not result.is_allowed
        assert result.decision == AccessDecision.DENIED_FEATURE_BLOCKED

    def test_sponsor_daily_limit_enforced(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_feature_access(
            persona_role="sponsor",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            messages_used_today=25,  # sponsor default limit is 25
        )
        assert not result.is_allowed
        assert result.decision == AccessDecision.DENIED_DAILY_LIMIT

    def test_sponsor_under_limit_allowed(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_feature_access(
            persona_role="sponsor",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            messages_used_today=10,
        )
        assert result.is_allowed
        assert result.remaining_messages == 15

    def test_owner_unlimited_messages(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            messages_used_today=9999,
        )
        assert result.is_allowed
        assert result.remaining_messages == -1  # unlimited

    def test_agent_blocked_for_sponsor(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_agent_access(
            persona_role="sponsor",
            agent_type="financial_agent",
            config=config,
        )
        assert not result.is_allowed
        assert result.decision == AccessDecision.DENIED_AGENT_BLOCKED

    def test_agent_allowed_for_owner(self):
        config = WorkspaceAIConfig()
        result = self.policy.check_agent_access(
            persona_role="owner",
            agent_type="financial_agent",
            config=config,
        )
        assert result.is_allowed

    def test_custom_persona_limits_from_config(self):
        config = WorkspaceAIConfig.from_dict({
            "persona_limits": {
                "sponsor": {
                    "can_use_chat": False,
                },
            },
        })
        result = self.policy.check_feature_access(
            persona_role="sponsor",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
        )
        assert not result.is_allowed
        assert result.decision == AccessDecision.DENIED_FEATURE_BLOCKED

    def test_effective_max_tokens(self):
        config = WorkspaceAIConfig(max_tokens=4000)
        tokens = self.policy.get_effective_max_tokens(
            persona_role="sponsor",
            config=config,
        )
        # Sponsor default is 2000, config max is 4000 → min(2000, 4000) = 2000
        assert tokens == 2000

    def test_effective_max_tokens_owner(self):
        config = WorkspaceAIConfig(max_tokens=4000)
        tokens = self.policy.get_effective_max_tokens(
            persona_role="owner",
            config=config,
        )
        # Owner default is 8000, config max is 4000 → min(8000, 4000) = 4000
        assert tokens == 4000

    # ── Workspace-level cost gates (the GTM 429 path, PR #5) ──────

    def test_workspace_daily_message_cap_blocks_at_limit(self):
        config = WorkspaceAIConfig(workspace_daily_message_budget=100)
        result = self.policy.check_feature_access(
            persona_role="owner",  # unlimited per-persona — only workspace cap bites
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            workspace_messages_today=100,
        )
        assert not result.is_allowed
        assert (
            result.decision
            == AccessDecision.DENIED_WORKSPACE_DAILY_MESSAGE_LIMIT
        )
        assert result.is_workspace_quota_exceeded
        assert result.workspace_daily_remaining_messages == 0

    def test_workspace_daily_message_cap_allows_under_limit(self):
        config = WorkspaceAIConfig(workspace_daily_message_budget=100)
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            workspace_messages_today=80,
        )
        assert result.is_allowed
        assert result.workspace_daily_remaining_messages == 20

    def test_workspace_daily_zero_budget_is_unlimited(self):
        # ``workspace_daily_message_budget == 0`` means "unlimited" so
        # the workspace cap never bites — the contract surface for
        # enterprise tiers that don't want a daily cap at all.
        config = WorkspaceAIConfig(workspace_daily_message_budget=0)
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            workspace_messages_today=999_999,
        )
        assert result.is_allowed
        assert result.workspace_daily_remaining_messages == -1

    def test_workspace_monthly_token_cap_blocks_at_limit(self):
        config = WorkspaceAIConfig(monthly_token_budget=1_000_000)
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            workspace_messages_today=0,
            workspace_tokens_this_month=1_000_000,
        )
        assert not result.is_allowed
        assert (
            result.decision
            == AccessDecision.DENIED_WORKSPACE_MONTHLY_TOKEN_LIMIT
        )
        assert result.is_workspace_quota_exceeded
        assert result.workspace_monthly_remaining_tokens == 0

    def test_workspace_monthly_token_cap_under_limit(self):
        config = WorkspaceAIConfig(monthly_token_budget=1_000_000)
        result = self.policy.check_feature_access(
            persona_role="owner",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            workspace_tokens_this_month=200_000,
        )
        assert result.is_allowed
        assert result.workspace_monthly_remaining_tokens == 800_000

    def test_persona_cap_checked_before_workspace_cap(self):
        # A sponsor at their per-seat 25/day limit gets DENIED_DAILY_LIMIT
        # (403), NOT the workspace-level 429 — even when the workspace
        # also happens to be at its cap. The per-persona cap is a config
        # decision the workspace owner can change; reaching it first
        # keeps the error message actionable for the sponsor user.
        config = WorkspaceAIConfig(workspace_daily_message_budget=100)
        result = self.policy.check_feature_access(
            persona_role="sponsor",
            feature=AIFeature.WORKSPACE_CHAT,
            config=config,
            messages_used_today=25,  # at sponsor's per-day cap
            workspace_messages_today=100,  # workspace also at cap
        )
        assert not result.is_allowed
        assert result.decision == AccessDecision.DENIED_DAILY_LIMIT
        assert not result.is_workspace_quota_exceeded
