"""Tests for workspace-level agent entitlements."""
from __future__ import annotations

import pytest

from components.agents.infrastructure.services.agent_entitlements import ensure_workspace_agent_type, resolve_agent_type
from components.agents.infrastructure.services.agents_service import get_agent_service
from infrastructure.persistence.sectors.models import Sector


@pytest.mark.django_db
def test_agent_service_blocks_explicitly_disabled_agent(workspace_factory, user_factory):
    """Explicit ``is_enabled=False`` row blocks (paid-feature /
    customer-disable / staged-rollout mechanism).

    Pre-2026-05-08 this test covered the absent-row case as well —
    "no entitlement = blocked". That semantic was flipped to
    opt-out (no row = enabled) so per-task agent routing can land
    on specialists like ``budget_agent`` without manual seeding.
    See ``resolve_agent_entitlement`` for the rationale.
    """
    owner = user_factory()
    workspace = workspace_factory(owner=owner, ai_teammate_enabled=True)

    service = get_agent_service()
    service.list_available_agent_types()
    agent_type = resolve_agent_type("task_agent")
    assert agent_type is not None
    # Explicit opt-out — the customer (or admin) chose to disable
    # this specialist on this workspace.
    ensure_workspace_agent_type(
        str(workspace.id), agent_type, is_enabled=False, updated_by=owner
    )

    with pytest.raises(PermissionError):
        service.create_agent(
            agent_type="task_agent",
            user_id=str(owner.id),
            workspace_id=str(workspace.id),
            config={},
        )


@pytest.mark.django_db
def test_agent_service_allows_specialist_without_explicit_entitlement(
    workspace_factory, user_factory
):
    """The 2026-05-08 regression shape, pinned.

    With per-task agent routing, the planner now picks specialists
    like ``budget_agent`` automatically. New workspaces don't have
    explicit ``WorkspaceAgentType`` rows for every specialist —
    they only have whatever ``ensure_ai_identity`` / setup wired in.
    Pre-fix, the absent-row case was "deny", which meant every chat
    that routed to a non-default agent crashed with
    ``"Agent type 'X' is not enabled for this organization."``

    The flipped default makes the absent-row case "allow", so
    specialists work out of the box. ``ai_teammate_enabled``,
    sector gates, and ``AgentType.is_active`` still apply as
    primary controls.
    """
    owner = user_factory()
    workspace = workspace_factory(owner=owner, ai_teammate_enabled=True)
    service = get_agent_service()
    service.list_available_agent_types()
    # No ``ensure_workspace_agent_type`` call — absent row.

    agent = service.create_agent(
        agent_type="budget_agent",
        user_id=str(owner.id),
        workspace_id=str(workspace.id),
        config={},
    )
    assert agent["agent_type"] == "budget_agent"


@pytest.mark.django_db
def test_agent_service_allows_enabled_agent(workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner, ai_teammate_enabled=True)
    service = get_agent_service()
    service.list_available_agent_types()
    agent_type = resolve_agent_type("task_agent")
    assert agent_type is not None
    ensure_workspace_agent_type(str(workspace.id), agent_type, is_enabled=True, updated_by=owner)

    agent = service.create_agent(
        agent_type="task_agent",
        user_id=str(owner.id),
        workspace_id=str(workspace.id),
        config={},
    )

    assert agent["agent_type"] == "task_agent"


@pytest.mark.django_db
def test_list_workspace_agent_types_marks_enabled(workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner, ai_teammate_enabled=True)
    service = get_agent_service()
    service.list_available_agent_types()
    agent_type = resolve_agent_type("task_agent")
    assert agent_type is not None
    ensure_workspace_agent_type(str(workspace.id), agent_type, is_enabled=True, updated_by=owner)

    catalogue = service.list_workspace_agent_types(str(workspace.id))

    task_entry = next(entry for entry in catalogue if entry["slug"] == "task_agent")
    orchestrator_entry = next(entry for entry in catalogue if entry["slug"] == "ai_teammate")

    assert task_entry["is_enabled"] is True
    assert orchestrator_entry["is_enabled"] is True


@pytest.mark.django_db
def test_sector_block_list_denies_entitled_agent(workspace_factory, user_factory):
    owner = user_factory()
    sector = Sector.objects.create(
        slug="education-blocklist-test",
        name="Education (Blocklist)",
        config={"blocked_agents": ["task_agent"]},
    )
    workspace = workspace_factory(owner=owner, ai_teammate_enabled=True, sector=sector)

    service = get_agent_service()
    service.list_available_agent_types()
    agent_type = resolve_agent_type("task_agent")
    assert agent_type is not None
    ensure_workspace_agent_type(str(workspace.id), agent_type, is_enabled=True, updated_by=owner)

    with pytest.raises(PermissionError):
        service.create_agent(
            agent_type="task_agent",
            user_id=str(owner.id),
            workspace_id=str(workspace.id),
            config={},
        )


@pytest.mark.django_db
def test_sector_allow_list_limits_enabled_agents(workspace_factory, user_factory):
    owner = user_factory()
    sector = Sector.objects.create(
        slug="healthcare",
        name="Healthcare",
        config={"allowed_agents": ["task_agent"]},
    )
    workspace = workspace_factory(owner=owner, ai_teammate_enabled=True, sector=sector)

    service = get_agent_service()
    service.list_available_agent_types()
    task_type = resolve_agent_type("task_agent")
    budget_type = resolve_agent_type("budget_agent")
    assert task_type is not None
    assert budget_type is not None
    ensure_workspace_agent_type(str(workspace.id), task_type, is_enabled=True, updated_by=owner)
    ensure_workspace_agent_type(str(workspace.id), budget_type, is_enabled=True, updated_by=owner)

    agent = service.create_agent(
        agent_type="task_agent",
        user_id=str(owner.id),
        workspace_id=str(workspace.id),
        config={},
    )
    assert agent["agent_type"] == "task_agent"

    with pytest.raises(PermissionError):
        service.create_agent(
            agent_type="budget_agent",
            user_id=str(owner.id),
            workspace_id=str(workspace.id),
            config={},
        )
