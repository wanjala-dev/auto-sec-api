"""Project the code agent registry → the ``AgentType`` DB rows.

Why this exists: the ``@register_agent`` decorator + each agent's ``profile``
class attribute (its self-describing "agent card") are the SINGLE SOURCE OF
TRUTH for what agents exist. The ``AgentType`` table is the entitlement gate the
deep pipeline + detector cycle consult — it must mirror the registry, not be a
second hand-maintained list.

Before this, adding an agent meant: (1) write the decorated file AND (2) append
to a hardcoded ``DEFAULT_AGENT_TYPES`` list AND (3) reseed. That duplication is
the classic registry-pattern anti-pattern (a giant list you must edit). Now:
write one decorated file with a ``profile`` and it auto-syncs here — no list
edit. ``DEFAULT_AGENT_TYPES`` survives only as OPTIONAL per-slug overrides for
agents that need richer default_config than their ``profile`` provides.

Idempotent upsert — safe to run at boot and on demand (``sync_agent_types``
management command).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _registry_agent_cards() -> list[dict]:
    """Collapse the ``{name/alias: class}`` registry into one card per class.

    Returns ``[{slug, aliases, class_path, name, description, default_config}]``
    derived entirely from the decorator + the class ``profile``.
    """
    from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

    by_class: dict[type, dict] = {}
    for entry_name, cls in dict(AgentRegistry._agents).items():
        card = by_class.get(cls)
        if card is None:
            canonical = getattr(cls, "_canonical_agent_name", None) or entry_name
            profile = getattr(cls, "profile", None) or {}
            card = {
                "slug": canonical,
                "aliases": set(),
                "class_path": f"{cls.__module__}.{cls.__qualname__}",
                "name": profile.get("name") or canonical.replace("_", " ").title(),
                "description": profile.get("summary") or "",
                "default_config": {"profile": profile} if profile else {},
            }
            by_class[cls] = card
        if entry_name != card["slug"]:
            card["aliases"].add(entry_name)

    cards = []
    for card in by_class.values():
        card["aliases"] = sorted(card["aliases"])
        cards.append(card)
    return cards


def sync_agent_types_from_registry(*, overrides: dict[str, dict] | None = None) -> dict[str, int]:
    """Upsert an ``AgentType`` row for every agent in the code registry.

    ``overrides`` maps ``slug -> partial AgentType field dict`` (e.g. from
    ``DEFAULT_AGENT_TYPES``) to enrich the auto-derived card. Returns a small
    ``{created, updated}`` summary. Never raises on a single agent — one bad
    card must not block the rest.
    """
    from infrastructure.persistence.ai.agents.models import AgentType

    overrides = overrides or {}
    created = updated = 0

    for card in _registry_agent_cards():
        try:
            slug = card["slug"]
            ov = overrides.get(slug, {})
            fields = {
                "name": ov.get("name") or card["name"],
                "description": ov.get("description") or card["description"],
                "class_path": ov.get("class_path") or card["class_path"],
                "default_config": ov.get("default_config") or card["default_config"],
                "aliases": ov.get("aliases") or card["aliases"],
                "required_actions": ov.get("required_actions", []),
                "allowed_tools": ov.get("allowed_tools", []),
                "department_tags": ov.get("department_tags", []),
                "default_run_config": ov.get("default_run_config", {}),
                "is_active": True,
            }
            obj, was_created = AgentType.objects.get_or_create(slug=slug, defaults=fields)
            if was_created:
                created += 1
                continue
            changed = []
            for field, expected in fields.items():
                if getattr(obj, field) != expected:
                    setattr(obj, field, expected)
                    changed.append(field)
            if changed:
                obj.save(update_fields=changed)
                updated += 1
        except Exception:
            logger.exception("agent_type_sync failed for slug=%s", card.get("slug"))

    logger.info("agent_type_sync created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}
