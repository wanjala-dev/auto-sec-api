"""Unit tests for WorkspaceAIConfig and PersonaAILimits."""

from components.agents.domain.value_objects.workspace_ai_config import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PersonaAILimits,
    WorkspaceAIConfig,
)


class TestPersonaAILimits:
    def test_defaults(self):
        limits = PersonaAILimits()
        assert limits.can_use_chat is True
        assert limits.can_use_pdf_chat is True
        assert limits.can_use_deep_runs is False
        assert limits.max_messages_per_day == 50

    def test_unlimited(self):
        limits = PersonaAILimits(max_messages_per_day=0)
        assert limits.is_unlimited is True

    def test_limited(self):
        limits = PersonaAILimits(max_messages_per_day=25)
        assert limits.is_unlimited is False


class TestWorkspaceAIConfig:
    def test_defaults(self):
        config = WorkspaceAIConfig()
        assert config.ai_enabled is True
        assert config.preferred_provider == PROVIDER_OPENAI
        assert config.preferred_model == "gpt-4o-mini"
        assert config.feedback_enabled is True

    def test_from_dict_empty(self):
        config = WorkspaceAIConfig.from_dict(None)
        assert config.ai_enabled is True

    def test_from_dict_with_overrides(self):
        config = WorkspaceAIConfig.from_dict({
            "ai_enabled": False,
            "preferred_provider": PROVIDER_ANTHROPIC,
            "preferred_model": "claude-opus-4-20250514",
            "daily_token_budget": 1_000_000,
        })
        assert config.ai_enabled is False
        assert config.preferred_provider == PROVIDER_ANTHROPIC
        assert config.preferred_model == "claude-opus-4-20250514"
        assert config.daily_token_budget == 1_000_000

    def test_from_dict_with_persona_limits(self):
        config = WorkspaceAIConfig.from_dict({
            "persona_limits": {
                "sponsor": {
                    "can_use_chat": False,
                    "max_messages_per_day": 10,
                },
            },
        })
        sponsor_limits = config.get_limits_for_persona("sponsor")
        assert sponsor_limits.can_use_chat is False
        assert sponsor_limits.max_messages_per_day == 10

    def test_roundtrip_serialization(self):
        original = WorkspaceAIConfig(
            ai_enabled=False,
            preferred_provider=PROVIDER_ANTHROPIC,
            preferred_model="claude-sonnet-4-20250514",
            temperature=0.5,
        )
        data = original.to_dict()
        restored = WorkspaceAIConfig.from_dict(data)
        assert restored.ai_enabled == original.ai_enabled
        assert restored.preferred_provider == original.preferred_provider
        assert restored.preferred_model == original.preferred_model
        assert restored.temperature == original.temperature

    def test_get_limits_for_unknown_persona(self):
        config = WorkspaceAIConfig()
        limits = config.get_limits_for_persona("unknown_role")
        assert isinstance(limits, PersonaAILimits)
        assert limits.can_use_chat is True  # default fallback

    def test_is_model_valid(self):
        config = WorkspaceAIConfig(
            preferred_provider=PROVIDER_OPENAI,
            preferred_model="gpt-4o",
        )
        assert config.is_model_valid() is True

    def test_is_model_invalid(self):
        config = WorkspaceAIConfig(
            preferred_provider=PROVIDER_OPENAI,
            preferred_model="nonexistent-model",
        )
        assert config.is_model_valid() is False
