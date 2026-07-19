"""Project the code agent registry onto the ``AgentType`` DB rows.

Run on deploy (or any time an agent is added/changed) to make every
``@register_agent`` agent entitlement-resolvable without touching a hardcoded
list. Idempotent. The app-ready hook + the lazy ``_load_agent_types`` path also
run this, so the command is mainly for explicit deploy-time sync + visibility.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Sync AgentType rows from the code agent registry (single source of truth)."

    def handle(self, *args, **options):
        from components.agents.application.config.agent_defaults import DEFAULT_AGENT_TYPES
        from components.agents.infrastructure.adapters.langchain.agents import discover_agents
        from components.agents.infrastructure.services.agent_type_sync import (
            sync_agent_types_from_registry,
        )
        from infrastructure.persistence.ai.agents.models import AgentType

        discover_agents()
        result = sync_agent_types_from_registry(overrides={d["slug"]: d for d in DEFAULT_AGENT_TYPES})
        slugs = sorted(AgentType.objects.filter(is_active=True).values_list("slug", flat=True))
        self.stdout.write(
            self.style.SUCCESS(
                f"synced agent types: created={result['created']} updated={result['updated']} "
                f"| active={len(slugs)}: {', '.join(slugs)}"
            )
        )
