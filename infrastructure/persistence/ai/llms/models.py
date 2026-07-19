"""AI Model catalog — platform-managed LLM models available for workspace selection.

Platform admins seed this table with models the platform supports (has API keys for).
Workspace owners then pick from this catalog when configuring their AI settings.
"""

from django.db import models


class AIModelProvider(models.Model):
    """LLM provider (OpenAI, Anthropic, Azure, Ollama, etc.)."""

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    logo_url = models.URLField(blank=True)
    is_active = models.BooleanField(
        default=True,
        help_text="Platform-level toggle. False = provider not available to any workspace.",
    )
    config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Provider-level config (e.g. base_url for Ollama, deployment info for Azure).",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_model_providers"
        ordering = ["name"]

    def __str__(self):
        return self.name


class AIModel(models.Model):
    """Individual LLM model that workspace owners can select.

    Seeded by platform admins. Only models with ``is_available=True``
    appear in the workspace AI configuration UI.
    """

    TIER_CHOICES = [
        ("tier_1", "Tier 1 — Fast & cheap"),
        ("tier_2", "Tier 2 — Balanced"),
        ("tier_3", "Tier 3 — Most capable"),
    ]

    slug = models.SlugField(max_length=100, unique=True)
    name = models.CharField(max_length=150, help_text="Human-friendly display name.")
    provider = models.ForeignKey(
        AIModelProvider,
        on_delete=models.CASCADE,
        related_name="models",
    )
    model_id = models.CharField(
        max_length=200,
        help_text="The exact model ID sent to the provider API (e.g. 'gpt-4o', 'claude-opus-4-20250514').",
    )
    description = models.TextField(blank=True)
    tier = models.CharField(max_length=10, choices=TIER_CHOICES, default="tier_2")

    # Capabilities
    supports_streaming = models.BooleanField(default=True)
    supports_tool_use = models.BooleanField(default=True)
    supports_vision = models.BooleanField(default=False)
    context_window = models.PositiveIntegerField(
        default=128000,
        help_text="Max context window in tokens.",
    )
    max_output_tokens = models.PositiveIntegerField(
        default=4096,
        help_text="Max output tokens per request.",
    )

    # Cost (for display and budget estimation)
    input_cost_per_1k = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text="Cost per 1K input tokens in USD.",
    )
    output_cost_per_1k = models.DecimalField(
        max_digits=10, decimal_places=6, default=0,
        help_text="Cost per 1K output tokens in USD.",
    )

    # Availability
    is_available = models.BooleanField(
        default=False,
        help_text="True when the platform has API keys configured and the model is ready to use.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="The default model for new workspaces that haven't configured AI yet.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "ai_models"
        ordering = ["provider", "tier", "name"]
        indexes = [
            models.Index(fields=["is_available", "provider"], name="ai_model_avail_provider_idx"),
            models.Index(fields=["is_default"], name="ai_model_default_idx"),
        ]

    def __str__(self):
        status = "available" if self.is_available else "unavailable"
        return f"{self.name} ({self.provider.slug}) [{status}]"
