"""Workspace-level agent enablement helpers.

Infrastructure service — all logic here touches the ORM directly.
Application-layer callers should import from the re-export shim at
``components.agents.application.policies.agent_entitlements``.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from django.contrib.auth import get_user_model
from django.db.utils import NotSupportedError

from infrastructure.persistence.ai.agents.models import AgentType, WorkspaceAgentType

try:
    from infrastructure.persistence.workspaces.models import Workspace
except ImportError:  # pragma: no cover
    Workspace = None

User = get_user_model()


def resolve_agent_type(slug: str) -> Optional[AgentType]:
    """Resolve an AgentType by slug or alias."""
    if not slug:
        return None
    agent_type = AgentType.objects.filter(slug=slug).first()
    if agent_type:
        return agent_type
    try:
        return AgentType.objects.filter(aliases__contains=[slug]).first()
    except NotSupportedError:
        for candidate in AgentType.objects.all():
            aliases = candidate.aliases or []
            if slug in aliases:
                return candidate
    return None


def _get_workspace(workspace_id: str):
    if not Workspace:
        return None
    queryset = getattr(Workspace, "_base_manager", None) or Workspace.objects
    return queryset.filter(id=workspace_id).first()


def _coerce_agent_list(raw) -> set[str]:
    if not raw:
        return set()
    if isinstance(raw, str):
        raw = [raw]
    items = set()
    for entry in raw:
        slug = str(entry or "").strip().lower()
        if not slug:
            continue
        resolved = resolve_agent_type(slug)
        items.add(resolved.slug if resolved else slug)
    return items


def ensure_workspace_agent_type(
    workspace_id: str,
    agent_type: AgentType,
    *,
    is_enabled: bool,
    updated_by: Optional[User] = None,
) -> WorkspaceAgentType:
    """Create or update a workspace entitlement for the given agent type."""
    defaults = {"is_enabled": is_enabled, "updated_by": updated_by}
    entitlement, _ = WorkspaceAgentType.objects.get_or_create(
        workspace_id=workspace_id,
        agent_type=agent_type,
        defaults=defaults,
    )
    updates = []
    if entitlement.is_enabled != is_enabled:
        entitlement.is_enabled = is_enabled
        updates.append("is_enabled")
    if updated_by and entitlement.updated_by_id != updated_by.id:
        entitlement.updated_by = updated_by
        updates.append("updated_by")
    if updates:
        entitlement.save(update_fields=[*updates, "updated_at"])
    return entitlement


def resolve_agent_entitlement(workspace_id: str, agent_slug: str) -> tuple[bool, str, Optional[str]]:
    """Resolve workspace entitlement and return (allowed, reason, canonical_slug).

    The workspace-level gate stack (in order):

    1. Workspace exists.
    2. Workspace has AI on (``Workspace.ai_teammate_enabled``).
    3. The ``AgentType`` is registered and active.
    4. There is no explicit ``WorkspaceAgentType`` row with
       ``is_enabled=False`` (explicit per-workspace opt-out).

    (The wanjala-era sector-level allow/block gate was removed in the
    sectors→domains rename: the domains M2M carries no config, so the
    gate always returned True — dead code reading a dropped field.)

    The semantics on (4) are deliberately **opt-out**: if no row
    exists for this (workspace, agent_type) pair, the agent is
    enabled. Pre-fix this was opt-in (no row = denied), which meant
    every new workspace had to be manually granted every specialist
    one-by-one. With per-task agent routing (PR #75) the planner
    started picking specialists like ``budget_agent`` automatically,
    and every chat that landed on an unentitled specialist hit
    ``"Agent type 'X' is not enabled for this organization."`` —
    even though the workspace had AI on and the sector allowed it.
    Henry hit this 2026-05-08 immediately after PR #75 deployed.

    Explicit ``is_enabled=False`` rows still block — that's the
    paid-feature / staged-rollout / customer-disable mechanism.
    Existing rows with ``is_enabled=True`` continue to behave the
    same. The change only flips the default for the absent-row case.
    """
    workspace = _get_workspace(workspace_id)
    if not workspace:
        return False, "workspace_not_found", None
    if not getattr(workspace, "ai_teammate_enabled", False):
        return False, "workspace_ai_disabled", None

    if agent_slug == "ai_teammate":
        return True, "ok", "ai_teammate"

    agent_type = resolve_agent_type(agent_slug)
    if not agent_type:
        return False, "agent_type_not_found", None
    if not agent_type.is_active:
        return False, "agent_type_inactive", agent_type.slug
    entitlement = WorkspaceAgentType.objects.filter(
        workspace_id=workspace_id, agent_type=agent_type
    ).first()
    if entitlement and not entitlement.is_enabled:
        # Explicit opt-out wins.
        return False, "workspace_entitlement_disabled", agent_type.slug

    return True, "ok", agent_type.slug


def is_agent_enabled_for_workspace(workspace_id: str, agent_slug: str) -> bool:
    """Return True when the workspace has AI enabled and the agent is explicitly enabled."""
    allowed, _, _ = resolve_agent_entitlement(workspace_id, agent_slug)
    return allowed


def get_workspace_entitlement_map(workspace_id: str) -> Dict[str, WorkspaceAgentType]:
    entitlements = WorkspaceAgentType.objects.filter(workspace_id=workspace_id).select_related("agent_type")
    return {ent.agent_type.slug: ent for ent in entitlements}


def workspace_ai_enabled(workspace_id: str) -> bool:
    workspace = _get_workspace(workspace_id)
    return bool(workspace and getattr(workspace, "ai_teammate_enabled", False))


def workspace_ai_paused(workspace_id: str) -> bool:
    """True only when the workspace EXISTS and has AI switched off.

    Distinct from ``not workspace_ai_enabled(...)`` on purpose: a missing
    workspace row is "unknown", not "paused" — callers that gate execution
    (the deep-run entry points in ``AgentsService``) must not refuse a
    workspace-less/unknown context that the entitlement gate downstream
    will judge with full information.
    """
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        workspace = _get_workspace(workspace_id)
    except (DjangoValidationError, ValueError, TypeError):
        # Malformed / non-UUID id → "unknown", not "paused". The paused
        # gate must never turn an identifier glitch into an AI halt.
        return False
    if workspace is None:
        return False
    return not getattr(workspace, "ai_teammate_enabled", False)
