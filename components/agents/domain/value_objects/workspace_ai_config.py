"""Workspace-level AI configuration — owner-controlled settings.

This value object captures everything a workspace owner can configure
about AI usage in their organization:

- Which LLM provider/model to use
- Per-persona access limits (what sponsors vs admins can do)
- Token budgets and cost caps
- Master on/off toggle
- Feedback collection settings
- Conversation history retention

Pure domain — no ORM, no framework imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── Supported model providers and their slugs ──────────────────────────

PROVIDER_OPENAI = "openai"
PROVIDER_AZURE = "azure"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OLLAMA = "ollama"

ALL_PROVIDERS = frozenset({PROVIDER_OPENAI, PROVIDER_AZURE, PROVIDER_ANTHROPIC, PROVIDER_OLLAMA})

# Well-known model slugs (workspace owners pick from these)
AVAILABLE_MODELS: dict[str, list[str]] = {
    PROVIDER_OPENAI: [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    ],
    PROVIDER_ANTHROPIC: [
        "claude-opus-4-20250514",
        "claude-sonnet-4-20250514",
        "claude-haiku-4-5-20251001",
    ],
    PROVIDER_AZURE: [
        "gpt-4o",
        "gpt-4",
        "gpt-35-turbo",
    ],
    PROVIDER_OLLAMA: [
        "llama3.1",
        "llama3.1:70b",
        "mistral",
        "codellama",
    ],
}


@dataclass(frozen=True)
class PersonaAILimits:
    """Per-persona constraints on AI usage.

    Each persona role gets its own set of limits that the workspace
    owner can customise.
    """

    can_use_chat: bool = True               # Can use workspace AI chat
    can_use_pdf_chat: bool = True            # Can chat with PDF/RAG documents
    can_use_deep_runs: bool = False          # Can trigger multi-step deep runs
    can_view_ai_actions: bool = False        # Can see AI-generated actions
    max_messages_per_day: int = 50           # Daily message cap (0 = unlimited)
    max_tokens_per_message: int = 4000       # Max response tokens per message
    allowed_agent_types: list[str] = field(default_factory=list)  # Empty = all enabled
    blocked_agent_types: list[str] = field(default_factory=list)  # Explicit denials

    @property
    def is_unlimited(self) -> bool:
        return self.max_messages_per_day == 0


# ── Default limits per persona role ─────────────────────────────────

DEFAULT_PERSONA_LIMITS: dict[str, PersonaAILimits] = {
    "owner": PersonaAILimits(
        can_use_chat=True,
        can_use_pdf_chat=True,
        can_use_deep_runs=True,
        can_view_ai_actions=True,
        max_messages_per_day=0,  # unlimited
        max_tokens_per_message=8000,
    ),
    "admin": PersonaAILimits(
        can_use_chat=True,
        can_use_pdf_chat=True,
        can_use_deep_runs=True,
        can_view_ai_actions=True,
        max_messages_per_day=0,
        max_tokens_per_message=8000,
    ),
    "contributor": PersonaAILimits(
        can_use_chat=True,
        can_use_pdf_chat=True,
        can_use_deep_runs=False,
        can_view_ai_actions=False,
        max_messages_per_day=100,
        max_tokens_per_message=4000,
    ),
    "sponsor": PersonaAILimits(
        can_use_chat=True,
        can_use_pdf_chat=True,
        can_use_deep_runs=False,
        can_view_ai_actions=False,
        max_messages_per_day=25,
        max_tokens_per_message=2000,
        blocked_agent_types=["financial_agent", "budget_agent"],
    ),
    "personal": PersonaAILimits(
        can_use_chat=True,
        can_use_pdf_chat=True,
        can_use_deep_runs=True,
        can_view_ai_actions=True,
        max_messages_per_day=0,
        max_tokens_per_message=8000,
    ),
}


@dataclass(frozen=True)
class WorkspaceAIConfig:
    """Complete AI configuration for a workspace.

    Stored as JSON in ``Workspace`` or ``AITeammateProfile.config``
    and loaded/validated via this domain value object.
    """

    # ── Master toggle ────────────────────────────────────────────────
    ai_enabled: bool = True

    # ── Model selection (workspace owner's choice) ───────────────────
    preferred_provider: str = PROVIDER_OPENAI
    preferred_model: str = "gpt-4o-mini"
    fallback_model: str = "gpt-3.5-turbo"
    temperature: float = 0.3
    max_tokens: int = 4000

    # ── Per-persona limits ───────────────────────────────────────────
    persona_limits: dict[str, PersonaAILimits] = field(
        default_factory=lambda: dict(DEFAULT_PERSONA_LIMITS)
    )

    # ── Budget / cost caps ───────────────────────────────────────────
    # Workspace-level daily message cap is the user-facing limit; the
    # monthly token cap is the ops kill-switch (catches a chatty
    # workspace whose individual messages each blow the token budget).
    # Both stack on top of the per-persona caps in ``persona_limits`` —
    # workspace cap is "shared pool", persona cap is "per seat at the
    # table". 0 = unlimited for any of these.
    workspace_daily_message_budget: int = 100
    daily_token_budget: int = 500_000
    monthly_token_budget: int = 10_000_000
    daily_cost_cap_usd: float = 10.0
    monthly_cost_cap_usd: float = 200.0

    # ── Feature toggles ─────────────────────────────────────────────
    feedback_enabled: bool = True           # Allow thumbs up/down on responses
    conversation_history_as_rag: bool = True # Index conversations into vector store
    session_memory_enabled: bool = True     # Extract durable facts from chats
    auto_embedding_sync: bool = True        # Celery job indexes new content

    # ── Conversation retention ───────────────────────────────────────
    conversation_retention_days: int = 90   # 0 = keep forever

    # ── AI fluency profile (workspace-owner authored) ────────────────
    # Free-text fields the workspace owner edits in settings. The
    # planner injects them into ``context.workspace_profile`` on every
    # chat so every plan inherits the owner's intent.
    #
    # ``voice_tone`` is LEGACY — the canonical voice moved to the brand
    # kit (``WorkspaceTheme.voice_tone`` + ``voice_guidelines``; see the
    # theming 0004 data migration). The field is kept only so stored
    # JSON keeps parsing; no reader consumes it any more.
    #
    # ``beneficiary_language_rules`` is the user's free-text rule set
    # for talking about the people the org serves — the canonical
    # example here is "say 'recipient' not 'child'", which the planner
    # honours by avoiding the banned word.
    #
    # ``custom_system_prompt_addendum`` is a workspace-owner authored
    # block appended to the planner system prompt. Treat as guard-rail
    # extensions, not full prompt overrides.
    voice_tone: str = ""
    beneficiary_language_rules: str = ""
    custom_system_prompt_addendum: str = ""

    # ── Factory ──────────────────────────────────────────────────────

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> WorkspaceAIConfig:
        """Parse from JSON (e.g. AITeammateProfile.config or Workspace field)."""
        if not data or not isinstance(data, dict):
            return cls()

        persona_limits = dict(DEFAULT_PERSONA_LIMITS)
        raw_limits = data.get("persona_limits")
        if isinstance(raw_limits, dict):
            for role, overrides in raw_limits.items():
                if role in persona_limits and isinstance(overrides, dict):
                    base = DEFAULT_PERSONA_LIMITS.get(role, PersonaAILimits())
                    persona_limits[role] = PersonaAILimits(
                        can_use_chat=overrides.get("can_use_chat", base.can_use_chat),
                        can_use_pdf_chat=overrides.get("can_use_pdf_chat", base.can_use_pdf_chat),
                        can_use_deep_runs=overrides.get("can_use_deep_runs", base.can_use_deep_runs),
                        can_view_ai_actions=overrides.get("can_view_ai_actions", base.can_view_ai_actions),
                        max_messages_per_day=int(overrides.get("max_messages_per_day", base.max_messages_per_day)),
                        max_tokens_per_message=int(overrides.get("max_tokens_per_message", base.max_tokens_per_message)),
                        allowed_agent_types=overrides.get("allowed_agent_types", base.allowed_agent_types),
                        blocked_agent_types=overrides.get("blocked_agent_types", base.blocked_agent_types),
                    )

        return cls(
            ai_enabled=bool(data.get("ai_enabled", True)),
            preferred_provider=str(data.get("preferred_provider", PROVIDER_OPENAI)),
            preferred_model=str(data.get("preferred_model", "gpt-4o-mini")),
            fallback_model=str(data.get("fallback_model", "gpt-3.5-turbo")),
            temperature=float(data.get("temperature", 0.3)),
            max_tokens=int(data.get("max_tokens", 4000)),
            persona_limits=persona_limits,
            workspace_daily_message_budget=int(data.get("workspace_daily_message_budget", 100)),
            daily_token_budget=int(data.get("daily_token_budget", 500_000)),
            monthly_token_budget=int(data.get("monthly_token_budget", 10_000_000)),
            daily_cost_cap_usd=float(data.get("daily_cost_cap_usd", 10.0)),
            monthly_cost_cap_usd=float(data.get("monthly_cost_cap_usd", 200.0)),
            feedback_enabled=bool(data.get("feedback_enabled", True)),
            conversation_history_as_rag=bool(data.get("conversation_history_as_rag", True)),
            session_memory_enabled=bool(data.get("session_memory_enabled", True)),
            auto_embedding_sync=bool(data.get("auto_embedding_sync", True)),
            conversation_retention_days=int(data.get("conversation_retention_days", 90)),
            voice_tone=str(data.get("voice_tone") or ""),
            beneficiary_language_rules=str(data.get("beneficiary_language_rules") or ""),
            custom_system_prompt_addendum=str(data.get("custom_system_prompt_addendum") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON for persistence."""
        return {
            "ai_enabled": self.ai_enabled,
            "preferred_provider": self.preferred_provider,
            "preferred_model": self.preferred_model,
            "fallback_model": self.fallback_model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "persona_limits": {
                role: {
                    "can_use_chat": limits.can_use_chat,
                    "can_use_pdf_chat": limits.can_use_pdf_chat,
                    "can_use_deep_runs": limits.can_use_deep_runs,
                    "can_view_ai_actions": limits.can_view_ai_actions,
                    "max_messages_per_day": limits.max_messages_per_day,
                    "max_tokens_per_message": limits.max_tokens_per_message,
                    "allowed_agent_types": limits.allowed_agent_types,
                    "blocked_agent_types": limits.blocked_agent_types,
                }
                for role, limits in self.persona_limits.items()
            },
            "workspace_daily_message_budget": self.workspace_daily_message_budget,
            "daily_token_budget": self.daily_token_budget,
            "monthly_token_budget": self.monthly_token_budget,
            "daily_cost_cap_usd": self.daily_cost_cap_usd,
            "monthly_cost_cap_usd": self.monthly_cost_cap_usd,
            "feedback_enabled": self.feedback_enabled,
            "conversation_history_as_rag": self.conversation_history_as_rag,
            "session_memory_enabled": self.session_memory_enabled,
            "auto_embedding_sync": self.auto_embedding_sync,
            "conversation_retention_days": self.conversation_retention_days,
            "voice_tone": self.voice_tone,
            "beneficiary_language_rules": self.beneficiary_language_rules,
            "custom_system_prompt_addendum": self.custom_system_prompt_addendum,
        }

    def get_limits_for_persona(self, persona_role: str) -> PersonaAILimits:
        """Return the AI limits for a given persona role."""
        return self.persona_limits.get(
            persona_role,
            DEFAULT_PERSONA_LIMITS.get(persona_role, PersonaAILimits()),
        )

    def is_model_valid(self) -> bool:
        """Check if the preferred model is in the known model list."""
        models = AVAILABLE_MODELS.get(self.preferred_provider, [])
        return self.preferred_model in models if models else True

