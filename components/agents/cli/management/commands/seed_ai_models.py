"""Seed the AI model catalog with supported providers and models.

Usage::

    python manage.py seed_ai_models              # Seed all
    python manage.py seed_ai_models --dry-run    # Preview without saving
    python manage.py seed_ai_models --available   # Mark seeded models as available

Only models that the platform has API keys for should be marked ``is_available=True``.
Run with ``--available`` when you've configured the keys.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

# ── Provider definitions ─────────────────────────────────────────────

PROVIDERS = [
    {
        "slug": "openai",
        "name": "OpenAI",
        "description": "GPT models from OpenAI.",
    },
    {
        "slug": "anthropic",
        "name": "Anthropic",
        "description": "Claude models from Anthropic.",
    },
    {
        "slug": "azure",
        "name": "Azure OpenAI",
        "description": "OpenAI models hosted on Microsoft Azure.",
    },
    {
        "slug": "ollama",
        "name": "Ollama (Self-hosted)",
        "description": "Open-source models running locally via Ollama.",
    },
]

# ── Model definitions ────────────────────────────────────────────────

MODELS = [
    # OpenAI
    {
        "slug": "gpt-4o",
        "name": "GPT-4o",
        "provider_slug": "openai",
        "model_id": "gpt-4o",
        "description": "Most capable OpenAI model. Fast, multimodal, great at reasoning.",
        "tier": "tier_3",
        "supports_vision": True,
        "context_window": 128000,
        "max_output_tokens": 16384,
        "input_cost_per_1k": 0.0025,
        "output_cost_per_1k": 0.01,
        "is_default": True,
    },
    {
        "slug": "gpt-4o-mini",
        "name": "GPT-4o Mini",
        "provider_slug": "openai",
        "model_id": "gpt-4o-mini",
        "description": "Small, fast, affordable. Great for most workspace tasks.",
        "tier": "tier_1",
        "supports_vision": True,
        "context_window": 128000,
        "max_output_tokens": 16384,
        "input_cost_per_1k": 0.00015,
        "output_cost_per_1k": 0.0006,
    },
    {
        "slug": "gpt-4-turbo",
        "name": "GPT-4 Turbo",
        "provider_slug": "openai",
        "model_id": "gpt-4-turbo",
        "description": "Previous-gen flagship. Strong at complex reasoning and long context.",
        "tier": "tier_3",
        "supports_vision": True,
        "context_window": 128000,
        "max_output_tokens": 4096,
        "input_cost_per_1k": 0.01,
        "output_cost_per_1k": 0.03,
    },
    {
        "slug": "gpt-3-5-turbo",
        "name": "GPT-3.5 Turbo",
        "provider_slug": "openai",
        "model_id": "gpt-3.5-turbo",
        "description": "Legacy fast model. Cheap but less capable.",
        "tier": "tier_1",
        "context_window": 16385,
        "max_output_tokens": 4096,
        "input_cost_per_1k": 0.0005,
        "output_cost_per_1k": 0.0015,
    },
    # Anthropic
    {
        "slug": "claude-opus-4",
        "name": "Claude Opus 4",
        "provider_slug": "anthropic",
        "model_id": "claude-opus-4-20250514",
        "description": "Most capable Claude model. Excels at complex analysis, planning, and coding.",
        "tier": "tier_3",
        "context_window": 200000,
        "max_output_tokens": 32768,
        "input_cost_per_1k": 0.015,
        "output_cost_per_1k": 0.075,
    },
    {
        "slug": "claude-sonnet-4",
        "name": "Claude Sonnet 4",
        "provider_slug": "anthropic",
        "model_id": "claude-sonnet-4-20250514",
        "description": "Balanced Claude model. Great reasoning at lower cost.",
        "tier": "tier_2",
        "context_window": 200000,
        "max_output_tokens": 16384,
        "input_cost_per_1k": 0.003,
        "output_cost_per_1k": 0.015,
    },
    {
        "slug": "claude-haiku-4-5",
        "name": "Claude Haiku 4.5",
        "provider_slug": "anthropic",
        "model_id": "claude-haiku-4-5-20251001",
        "description": "Fastest Claude model. Best for simple tasks and high-volume use.",
        "tier": "tier_1",
        "context_window": 200000,
        "max_output_tokens": 8192,
        "input_cost_per_1k": 0.001,
        "output_cost_per_1k": 0.005,
    },
    # Azure OpenAI
    {
        "slug": "azure-gpt-4o",
        "name": "Azure GPT-4o",
        "provider_slug": "azure",
        "model_id": "gpt-4o",
        "description": "GPT-4o hosted on Azure. Same capabilities, enterprise compliance.",
        "tier": "tier_3",
        "supports_vision": True,
        "context_window": 128000,
        "max_output_tokens": 16384,
        "input_cost_per_1k": 0.0025,
        "output_cost_per_1k": 0.01,
    },
    {
        "slug": "azure-gpt-35-turbo",
        "name": "Azure GPT-3.5 Turbo",
        "provider_slug": "azure",
        "model_id": "gpt-35-turbo",
        "description": "GPT-3.5 on Azure. Fast and cheap for simple tasks.",
        "tier": "tier_1",
        "context_window": 16385,
        "max_output_tokens": 4096,
        "input_cost_per_1k": 0.0005,
        "output_cost_per_1k": 0.0015,
    },
    # Ollama (self-hosted)
    {
        "slug": "llama-3-1",
        "name": "Llama 3.1 (8B)",
        "provider_slug": "ollama",
        "model_id": "llama3.1",
        "description": "Meta's open-source model. Free to run, good general assistant.",
        "tier": "tier_1",
        "context_window": 128000,
        "max_output_tokens": 4096,
        "input_cost_per_1k": 0,
        "output_cost_per_1k": 0,
    },
    {
        "slug": "llama-3-1-70b",
        "name": "Llama 3.1 (70B)",
        "provider_slug": "ollama",
        "model_id": "llama3.1:70b",
        "description": "Larger Llama. Near GPT-4 quality, self-hosted.",
        "tier": "tier_2",
        "context_window": 128000,
        "max_output_tokens": 4096,
        "input_cost_per_1k": 0,
        "output_cost_per_1k": 0,
    },
    {
        "slug": "mistral",
        "name": "Mistral 7B",
        "provider_slug": "ollama",
        "model_id": "mistral",
        "description": "Fast open-source model. Good for simple tasks.",
        "tier": "tier_1",
        "context_window": 32000,
        "max_output_tokens": 4096,
        "input_cost_per_1k": 0,
        "output_cost_per_1k": 0,
    },
    {
        "slug": "codellama",
        "name": "Code Llama",
        "provider_slug": "ollama",
        "model_id": "codellama",
        "description": "Specialized for code generation and analysis.",
        "tier": "tier_2",
        "supports_tool_use": False,
        "context_window": 16000,
        "max_output_tokens": 4096,
        "input_cost_per_1k": 0,
        "output_cost_per_1k": 0,
    },
]


class Command(BaseCommand):
    help = "Seed the AI model catalog with supported providers and models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview changes without writing to the database.",
        )
        parser.add_argument(
            "--available",
            action="store_true",
            help="Mark all seeded models as available (use when API keys are configured).",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        from infrastructure.persistence.ai.llms.models import AIModel, AIModelProvider

        dry_run = options["dry_run"]
        mark_available = options["available"]

        providers_created = 0
        models_created = 0
        models_updated = 0

        # Seed providers
        provider_map = {}
        for prov_data in PROVIDERS:
            if dry_run:
                self.stdout.write(f"  [DRY RUN] Would seed provider: {prov_data['slug']}")
                continue
            obj, created = AIModelProvider.objects.update_or_create(
                slug=prov_data["slug"],
                defaults={
                    "name": prov_data["name"],
                    "description": prov_data.get("description", ""),
                },
            )
            provider_map[prov_data["slug"]] = obj
            if created:
                providers_created += 1

        if not dry_run:
            # Also load existing providers for model FK resolution
            for p in AIModelProvider.objects.all():
                provider_map.setdefault(p.slug, p)

        # Seed models
        for model_data in MODELS:
            provider_slug = model_data.pop("provider_slug")
            provider = provider_map.get(provider_slug)
            if dry_run:
                self.stdout.write(f"  [DRY RUN] Would seed model: {model_data['slug']} ({provider_slug})")
                continue
            if not provider:
                self.stderr.write(f"  SKIP: Provider {provider_slug} not found for model {model_data['slug']}")
                continue

            defaults = {
                "name": model_data["name"],
                "provider": provider,
                "model_id": model_data["model_id"],
                "description": model_data.get("description", ""),
                "tier": model_data.get("tier", "tier_2"),
                "supports_streaming": model_data.get("supports_streaming", True),
                "supports_tool_use": model_data.get("supports_tool_use", True),
                "supports_vision": model_data.get("supports_vision", False),
                "context_window": model_data.get("context_window", 128000),
                "max_output_tokens": model_data.get("max_output_tokens", 4096),
                "input_cost_per_1k": model_data.get("input_cost_per_1k", 0),
                "output_cost_per_1k": model_data.get("output_cost_per_1k", 0),
                "is_default": model_data.get("is_default", False),
            }
            if mark_available:
                defaults["is_available"] = True

            obj, created = AIModel.objects.update_or_create(
                slug=model_data["slug"],
                defaults=defaults,
            )
            if created:
                models_created += 1
            else:
                models_updated += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(
                f"\n[DRY RUN] Would seed {len(PROVIDERS)} providers and {len(MODELS)} models."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"\nSeeded {providers_created} providers, "
                f"created {models_created} models, "
                f"updated {models_updated} models."
            ))
            if mark_available:
                self.stdout.write(self.style.SUCCESS("All models marked as available."))
