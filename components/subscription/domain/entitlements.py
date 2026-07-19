"""Plan entitlements — data-driven numeric limits (no framework imports).

This is the single source of truth for *how* a subscription tier's numeric
quotas are represented and resolved. It replaces the three hard-coded
``Plan.max_*`` columns with an extensible, data-driven map so that adding a
new quota dimension (recipients, campaigns, storage, AI runs…) is a new
``EntitlementKey`` member + seed data, NOT a schema migration touched in a
dozen files.

Scope: NUMERIC limits only. Boolean tier features ride the existing
``FeatureFlag`` / ``FeatureFlagRule`` system (which already does
user → workspace → global → default resolution); we do not build a second
boolean-gating mechanism here.

Resolution order (see :class:`EntitlementsResolver`):

    base (unlimited)  ←  plan limits  ←  workspace overrides

``None`` / an absent key means UNLIMITED. A legacy ``0`` is normalised to
unlimited too, because the old ``IntegerField(default=0)`` column used 0 as
the "unset / no limit" sentinel (the enforcement guard was
``if max_projects and count >= max_projects``).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

# Sentinel: a limit of None (or an absent key) means "no cap".
UNLIMITED: None = None


class EntitlementKey(str, Enum):
    """Canonical registry of numeric quota dimensions.

    Add a new dimension here + seed it in :data:`TIER_CATALOG` and it flows
    everywhere through the resolver — no migration, no per-file edits.
    """

    MAX_PROJECTS_PER_TEAM = "max_projects_per_team"
    MAX_MEMBERS_PER_TEAM = "max_members_per_team"
    MAX_TASKS_PER_PROJECT = "max_tasks_per_project"
    # Metered AI: monthly agent-run allowance. Free tastes the differentiator,
    # Premium is unlimited (absent key / None). Enforced at the agent-execution
    # use case via EntitlementsResolver — see PREMIUM_FEATURE_TIERS_PLAN.md §5.
    MAX_AI_RUNS_PER_MONTH = "max_ai_runs_per_month"
    # Future dimensions (data, not schema) — uncomment + seed when needed:
    # MAX_TEAMS = "max_teams"
    # MAX_RECIPIENTS = "max_recipients"
    # MAX_CAMPAIGNS = "max_campaigns"
    # MAX_EVENTS = "max_events"
    # MAX_STORAGE_MB = "max_storage_mb"

    @classmethod
    def values(cls) -> tuple[str, ...]:
        return tuple(member.value for member in cls)


def _key(key: "EntitlementKey | str") -> str:
    return key.value if isinstance(key, EntitlementKey) else str(key)


def _normalise(value: object) -> int | None:
    """Coerce a raw limit value to a positive int or UNLIMITED.

    ``None`` → unlimited. ``0`` → unlimited (legacy sentinel). Non-numeric
    → unlimited (defensive). Positive int → that cap.
    """
    if value is None:
        return None
    try:
        ivalue = int(value)
    except (TypeError, ValueError):
        return None
    return ivalue if ivalue > 0 else None


@dataclass(frozen=True)
class PlanEntitlements:
    """Resolved numeric entitlements for a workspace.

    ``limits`` only carries keys with a real positive cap; any key not
    present is UNLIMITED.
    """

    limits: Mapping[str, int]

    def limit_for(self, key: "EntitlementKey | str") -> int | None:
        """Return the cap for ``key``, or ``None`` if unlimited."""
        return self.limits.get(_key(key))

    def is_unlimited(self, key: "EntitlementKey | str") -> bool:
        return self.limit_for(key) is None

    def is_within_limit(self, key: "EntitlementKey | str", current_count: int) -> bool:
        """True if one more may be created — i.e. ``current_count < cap``.

        Unlimited always permits. Mirrors the legacy guard
        ``count >= max`` ⇒ blocked.
        """
        cap = self.limit_for(key)
        return cap is None or current_count < cap

    def as_dict(self) -> dict[str, int | None]:
        """Every known key mapped to its cap (``None`` = unlimited).

        Used by serializers that must emit a value for every dimension.
        """
        return {key: self.limits.get(key) for key in EntitlementKey.values()}


class EntitlementsResolver:
    """Merge entitlement layers into a :class:`PlanEntitlements`.

    Layers are plain ``{key: int | None}`` mappings; later layers win.
    Unknown keys are ignored defensively so a stray override key can't
    inject an unrecognised quota.
    """

    @staticmethod
    def resolve(
        *,
        plan_limits: Mapping[str, object] | None = None,
        workspace_overrides: Mapping[str, object] | None = None,
    ) -> PlanEntitlements:
        merged: dict[str, int] = {}
        for layer in (plan_limits, workspace_overrides):
            if not layer:
                continue
            for raw_key, raw_value in layer.items():
                key = _key(raw_key)
                if key not in EntitlementKey.values():
                    continue
                normalised = _normalise(raw_value)
                if normalised is None:
                    # Explicit unlimited — drop any cap a lower layer set.
                    merged.pop(key, None)
                else:
                    merged[key] = normalised
        return PlanEntitlements(limits=merged)


# Canonical tier limit catalogue — the ONE definition of Free/Pro/Premium
# numeric quotas. Seeders and tests read this; nothing hard-codes the numbers
# in N places anymore. Limits ascend Free < Pro < Premium, where Premium is
# unlimited on every dimension (an empty map ⇒ no caps). See
# PREMIUM_FEATURE_TIERS_PLAN.md §2.
TIER_CATALOG: dict[str, dict[str, int]] = {
    "Free": {
        EntitlementKey.MAX_PROJECTS_PER_TEAM.value: 3,
        EntitlementKey.MAX_MEMBERS_PER_TEAM.value: 5,
        EntitlementKey.MAX_TASKS_PER_PROJECT.value: 10,
        EntitlementKey.MAX_AI_RUNS_PER_MONTH.value: 20,
    },
    "Pro": {
        EntitlementKey.MAX_PROJECTS_PER_TEAM.value: 25,
        EntitlementKey.MAX_MEMBERS_PER_TEAM.value: 50,
        EntitlementKey.MAX_TASKS_PER_PROJECT.value: 100,
        EntitlementKey.MAX_AI_RUNS_PER_MONTH.value: 200,
    },
    # Premium: unlimited on every dimension. An empty map resolves to no caps
    # (UNLIMITED) for all keys, including AI runs.
    "Premium": {},
}


def tier_limits(title: str) -> dict[str, int]:
    """Return a copy of the canonical limits for a tier title (case-insensitive).

    Unknown titles return an empty map (= unlimited), preserving the legacy
    "no plan ⇒ no block" behaviour.
    """
    return dict(TIER_CATALOG.get(title.strip().title(), {}))
