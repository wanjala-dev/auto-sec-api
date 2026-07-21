"""Integration tests — the workspace AI kill switch (vision §3.4).

The endpoint is the ACTOR side of the governance slice: owner/admin-gated
(``manage_agents``), flips ``Workspace.ai_teammate_enabled``, writes an
audit entry (actor + reason + timestamp), and returns the new status.
Flipping OFF must be respected end-to-end: the entitlement gate refuses,
the deep-run service entry points refuse, and the detector fan-out no
longer selects the workspace. Also pins the governance-slice addition that
capability PATCHes now leave an audit trail.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command

from components.agents.application.policies.agent_entitlements import (
    resolve_agent_entitlement,
)
from components.agents.application.service import AgentsService
from components.agents.domain.errors import AiUnavailable
from components.audit.infrastructure.services.audit_log import get_entity_history
from infrastructure.persistence.workspaces.models import WorkspaceMembership

URL = "/ai/agents/kill-switch/"


@pytest.fixture
def roles(db):
    # ``membership_has_permission`` resolves the legacy ``role`` string
    # against the seeded system WorkspaceRole rows; migrations don't run
    # under pytest, so seed them explicitly.
    call_command("seed_workspace_roles")


def _member(workspace, user, role="member"):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role, status="active")


@pytest.mark.django_db
class TestKillSwitchEndpointGating:
    def test_anonymous_denied(self, api_client, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        response = api_client.post(URL, {"workspace_id": str(workspace.id), "enabled": False, "reason": "x"})
        assert response.status_code in (401, 403)

    def test_member_role_cannot_flip(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        analyst = user_factory()
        _member(workspace, analyst, role="member")
        api_client.force_authenticate(analyst)

        response = api_client.post(
            URL, {"workspace_id": str(workspace.id), "enabled": False, "reason": "nope"}, format="json"
        )

        assert response.status_code == 403
        workspace.refresh_from_db()
        assert workspace.ai_teammate_enabled is True

    def test_member_role_can_read_status(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        analyst = user_factory()
        _member(workspace, analyst, role="member")
        api_client.force_authenticate(analyst)

        response = api_client.get(URL, {"workspace_id": str(workspace.id)})

        assert response.status_code == 200, response.data
        assert response.data["ai_teammate_enabled"] is True
        assert response.data["ai_halted"] is False

    def test_admin_role_can_flip(self, roles, api_client, workspace_factory, user_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        admin = user_factory()
        _member(workspace, admin, role="admin")
        api_client.force_authenticate(admin)

        response = api_client.post(
            URL,
            {"workspace_id": str(workspace.id), "enabled": False, "reason": "incident containment"},
            format="json",
        )

        assert response.status_code == 200, response.data
        workspace.refresh_from_db()
        assert workspace.ai_teammate_enabled is False


@pytest.mark.django_db
class TestKillSwitchFlip:
    def test_owner_flip_off_writes_audit_and_returns_status(self, api_client, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        owner = workspace.workspace_owner
        api_client.force_authenticate(owner)

        response = api_client.post(
            URL,
            {"workspace_id": str(workspace.id), "enabled": False, "reason": "AI misbehaving — pausing"},
            format="json",
        )

        assert response.status_code == 200, response.data
        assert response.data["ai_teammate_enabled"] is False
        assert response.data["ai_halted"] is True

        workspace.refresh_from_db()
        assert workspace.ai_teammate_enabled is False

        entries = get_entity_history(instance=workspace, field_name="ai_teammate_enabled")
        assert len(entries) == 1
        entry = entries[0]
        assert entry.previous_value is True
        assert entry.new_value is False
        assert entry.actor_id == str(owner.id)
        assert entry.reason == "AI misbehaving — pausing"
        assert entry.created_at is not None

    def test_flip_back_on_is_audited_too(self, api_client, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=False)
        api_client.force_authenticate(workspace.workspace_owner)

        response = api_client.post(
            URL, {"workspace_id": str(workspace.id), "enabled": True, "reason": "incident resolved"}, format="json"
        )

        assert response.status_code == 200, response.data
        assert response.data["ai_teammate_enabled"] is True
        workspace.refresh_from_db()
        assert workspace.ai_teammate_enabled is True

        entries = get_entity_history(instance=workspace, field_name="ai_teammate_enabled")
        assert next(e.new_value for e in entries) is True

    def test_reason_is_mandatory(self, api_client, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        api_client.force_authenticate(workspace.workspace_owner)

        response = api_client.post(URL, {"workspace_id": str(workspace.id), "enabled": False}, format="json")

        assert response.status_code == 400
        workspace.refresh_from_db()
        assert workspace.ai_teammate_enabled is True

    def test_enabled_must_be_boolean(self, api_client, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        api_client.force_authenticate(workspace.workspace_owner)

        response = api_client.post(
            URL, {"workspace_id": str(workspace.id), "enabled": "false", "reason": "x"}, format="json"
        )

        assert response.status_code == 400

    def test_unknown_workspace_is_404(self, api_client, user_factory):
        # A staff user bypasses the membership gate, so the use case's own
        # not-found branch is reachable.
        staff = user_factory()
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        api_client.force_authenticate(staff)

        response = api_client.post(
            URL,
            {"workspace_id": "00000000-0000-0000-0000-000000000001", "enabled": False, "reason": "x"},
            format="json",
        )

        assert response.status_code == 404

    def test_repeat_flip_is_idempotent_in_the_audit_record(self, api_client, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        api_client.force_authenticate(workspace.workspace_owner)

        for _ in range(2):
            response = api_client.post(
                URL, {"workspace_id": str(workspace.id), "enabled": False, "reason": "pause"}, format="json"
            )
            assert response.status_code == 200

        # The audit facade suppresses identical-value writes: one flip,
        # one row — a double-click never fabricates a second event.
        entries = get_entity_history(instance=workspace, field_name="ai_teammate_enabled")
        assert len(entries) == 1


@pytest.mark.django_db
class TestKillSwitchEnforcement:
    def test_entitlement_gate_blocks_when_off(self, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=False)

        allowed, reason, _ = resolve_agent_entitlement(str(workspace.id), "triage_agent")

        assert allowed is False
        assert reason == "workspace_ai_disabled"

    def test_deep_run_entry_points_refuse_when_off(self, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=False)

        with pytest.raises(AiUnavailable):
            AgentsService._raise_if_ai_killed(str(workspace.id))

    def test_deep_run_entry_points_allow_when_on(self, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)

        AgentsService._raise_if_ai_killed(str(workspace.id))  # does not raise

    def test_detector_fanout_skips_paused_workspace(self, workspace_factory):
        from components.agents.infrastructure.services.actions_service import get_ai_action_service
        from infrastructure.persistence.ai.models import AITeammateProfile

        paused = workspace_factory(ai_teammate_enabled=False)
        active = workspace_factory(ai_teammate_enabled=True)
        for workspace in (paused, active):
            AITeammateProfile.objects.create(
                workspace=workspace, user=workspace.workspace_owner, is_enabled=True, status="active"
            )

        scheduled_ids = {str(p.workspace_id) for p in get_ai_action_service().iter_enabled_seeds()}

        assert str(active.id) in scheduled_ids
        assert str(paused.id) not in scheduled_ids

    def test_flip_off_then_on_restores_dispatch(self, api_client, workspace_factory):
        workspace = workspace_factory(ai_teammate_enabled=True)
        api_client.force_authenticate(workspace.workspace_owner)

        api_client.post(URL, {"workspace_id": str(workspace.id), "enabled": False, "reason": "pause"}, format="json")
        with pytest.raises(AiUnavailable):
            AgentsService._raise_if_ai_killed(str(workspace.id))

        api_client.post(URL, {"workspace_id": str(workspace.id), "enabled": True, "reason": "resume"}, format="json")
        AgentsService._raise_if_ai_killed(str(workspace.id))  # does not raise
        allowed, _, _ = resolve_agent_entitlement(str(workspace.id), "ai_teammate")
        assert allowed is True


@pytest.mark.django_db
class TestCapabilityPatchAudit:
    def test_capability_patch_writes_audit_entry(self, workspace_factory):
        from components.agents.application.ports.agent_profile_port import (
            PatchAgentCapabilitiesCommand,
        )
        from infrastructure.persistence.ai.agents.models import Agent

        workspace = workspace_factory()
        agent = Agent.objects.create(
            workspace=workspace, user=workspace.workspace_owner, agent_type="triage_agent", config={}
        )

        AgentsService().patch_agent_capabilities(
            PatchAgentCapabilitiesCommand(
                agent_id=str(agent.agent_id),
                user=workspace.workspace_owner,
                data={"open_draft_pr": True},
            )
        )

        entries = get_entity_history(instance=agent, field_name="capabilities")
        assert len(entries) == 1
        entry = entries[0]
        assert entry.previous_value == {}
        assert entry.new_value == {"open_draft_pr": True}
        assert entry.actor_id == str(workspace.workspace_owner.id)
        assert entry.reason == "agent capability toggle via API"

    def test_governance_service_reads_the_grant_history(self, workspace_factory):
        from components.agents.application.ports.agent_profile_port import (
            PatchAgentCapabilitiesCommand,
        )
        from components.agents.application.services import ai_governance_service
        from infrastructure.persistence.ai.agents.models import Agent

        workspace = workspace_factory()
        agent = Agent.objects.create(
            workspace=workspace, user=workspace.workspace_owner, agent_type="triage_agent", config={}
        )
        AgentsService().patch_agent_capabilities(
            PatchAgentCapabilitiesCommand(
                agent_id=str(agent.agent_id),
                user=workspace.workspace_owner,
                data={"open_draft_pr": True},
            )
        )

        grants = ai_governance_service.capability_grants(str(workspace.id))

        row = next(r for r in grants["agents"] if r["agent_id"] == str(agent.agent_id))
        assert row["enabled_capabilities"] == ["open_draft_pr"]
        assert row["grant_history_recorded"] is True
        assert row["grant_audit_entries"][0]["new_value"] == {"open_draft_pr": True}
