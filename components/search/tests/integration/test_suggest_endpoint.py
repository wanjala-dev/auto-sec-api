"""Integration tests for GET /search/suggest/.

Covers: auth required, min query length, section shapes, workspace
scoping (member of A can't see B's members/findings), and the limit cap.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.ai.agents.models import Agent, AgentProfile
from infrastructure.persistence.ai.conversations.models import Conversation
from infrastructure.persistence.integrations.models import (
    AwsOrganizationConnection,
    LogPatternRollup,
)
from infrastructure.persistence.project.models import Column, Task
from infrastructure.persistence.workspaces.models import WorkspaceMembership

SUGGEST_URL = "/search/suggest/"


def _named_user(user_factory, first_name, last_name):
    # The fork's UserManager.create_user() only accepts username/email/password,
    # so names are assigned post-create.
    user = user_factory()
    user.first_name = first_name
    user.last_name = last_name
    user.save(update_fields=["first_name", "last_name"])
    return user


def _add_member(workspace, user, role=WorkspaceMembership.Role.MEMBER):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        persona="contributor",
        role=role,
        status=WorkspaceMembership.Status.ACTIVE,
    )


def _make_task(workspace, team, user, title, *, source_type="", metadata=None, column=None):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        created_by=user,
        title=title,
        source_type=source_type,
        metadata=metadata or {},
        column=column,
    )


@pytest.mark.django_db
class TestAuthAndValidation:
    def test_anonymous_request_is_rejected(self, api_client):
        response = api_client.get(SUGGEST_URL, {"q": "scan"})
        assert response.status_code == 401

    def test_short_query_returns_empty_sections(self, api_client, user_factory):
        user = user_factory()
        api_client.force_authenticate(user=user)

        response = api_client.get(SUGGEST_URL, {"q": "a"})

        assert response.status_code == 200
        assert response.data == {"sections": {}}


@pytest.mark.django_db
class TestSectionShapes:
    def test_findings_and_tasks_sections(self, api_client, workspace_factory, team_factory, user_factory):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        team = team_factory(workspace=workspace)
        _add_member(workspace, user, role=WorkspaceMembership.Role.OWNER)
        column = Column.objects.create(workspace=workspace, team=team, title="Triage", created_by=user)
        _make_task(
            workspace,
            team,
            user,
            "Suspicious login burst",
            source_type="ai.log_watch",
            metadata={"severity": "high", "payload": {"kind": "error"}},
        )
        _make_task(workspace, team, user, "Rotate suspicious credentials", column=column)
        api_client.force_authenticate(user=user)

        response = api_client.get(SUGGEST_URL, {"q": "suspicious"})

        assert response.status_code == 200
        sections = response.data["sections"]
        assert [f["title"] for f in sections["findings"]] == ["Suspicious login burst"]
        finding = sections["findings"][0]
        assert set(finding.keys()) == {"id", "title", "subtitle", "url"}
        assert finding["subtitle"] == "high · error"
        assert finding["url"] == "/?panel=kanban"
        task = sections["tasks"][0]
        assert task["title"] == "Rotate suspicious credentials"
        assert task["subtitle"] == "Triage"

    def test_agents_conversations_members_and_log_services(self, api_client, workspace_factory, user_factory):
        user = _named_user(user_factory, "Ada", "Analyst")
        workspace = workspace_factory(owner=user)
        _add_member(workspace, user, role=WorkspaceMembership.Role.ADMIN)

        agent = Agent.objects.create(agent_type="triage_agent", user=user, workspace=workspace)
        AgentProfile.objects.create(agent=agent, display_name="Sentinel Triage", summary="Watches logs")
        Conversation.objects.create(user=user, title="Sentinel incident thread")
        connection = AwsOrganizationConnection.objects.create(
            workspace=workspace,
            management_account_id="123456789012",
            external_id="ext-search-test-1",
            created_by=user,
        )
        LogPatternRollup.objects.create(
            connection=connection,
            workspace=workspace,
            service="sentinel-api",
            signature="sig-1",
        )
        api_client.force_authenticate(user=user)

        response = api_client.get(SUGGEST_URL, {"q": "sentinel"})

        assert response.status_code == 200
        sections = response.data["sections"]
        agent_item = sections["agents"][0]
        assert agent_item["title"] == "Sentinel Triage"
        assert agent_item["subtitle"] == "triage_agent"
        conversation_item = sections["conversations"][0]
        assert conversation_item["title"] == "Sentinel incident thread"
        log_item = sections["log_services"][0]
        assert log_item == {
            "id": "sentinel-api",
            "title": "sentinel-api",
            "subtitle": "log service",
            "url": "/?panel=documents",
        }

        # Member search matches on name and carries the role as subtitle.
        member_response = api_client.get(SUGGEST_URL, {"q": "ada"})
        member_item = member_response.data["sections"]["members"][0]
        assert member_item["title"] == "Ada Analyst"
        assert member_item["subtitle"] == "admin"
        assert member_item["url"] == "/?panel=settings&section=members"

    def test_empty_sections_are_omitted(self, api_client, workspace_factory, user_factory):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        _add_member(workspace, user)
        api_client.force_authenticate(user=user)

        response = api_client.get(SUGGEST_URL, {"q": "zzz-no-match"})

        assert response.status_code == 200
        assert response.data["sections"] == {}


@pytest.mark.django_db
class TestWorkspaceScoping:
    def test_member_of_a_cannot_see_bs_members_and_findings(
        self, api_client, workspace_factory, team_factory, user_factory
    ):
        member_a = _named_user(user_factory, "Alice", "Blue")
        owner_b = user_factory()
        member_b = _named_user(user_factory, "Alicia", "Bluefield")

        workspace_a = workspace_factory(owner=member_a)
        _add_member(workspace_a, member_a, role=WorkspaceMembership.Role.OWNER)

        workspace_b = workspace_factory(owner=owner_b)
        _add_member(workspace_b, owner_b, role=WorkspaceMembership.Role.OWNER)
        _add_member(workspace_b, member_b)
        team_b = team_factory(workspace=workspace_b)
        _make_task(workspace_b, team_b, owner_b, "Alicia flagged exfiltration", source_type="ai.log_watch")

        api_client.force_authenticate(user=member_a)
        response = api_client.get(SUGGEST_URL, {"q": "alic"})

        assert response.status_code == 200
        sections = response.data["sections"]
        member_titles = [m["title"] for m in sections.get("members", [])]
        assert member_titles == ["Alice Blue"]  # own membership only, no B leak
        assert "findings" not in sections

    def test_explicit_workspace_id_must_be_own_membership(self, api_client, workspace_factory, user_factory):
        requester = user_factory()
        outsider_owner = user_factory()
        own_workspace = workspace_factory(owner=requester)
        _add_member(own_workspace, requester)
        foreign_workspace = workspace_factory(owner=outsider_owner)
        _add_member(foreign_workspace, outsider_owner)

        api_client.force_authenticate(user=requester)
        response = api_client.get(SUGGEST_URL, {"q": "anything", "workspace_id": str(foreign_workspace.id)})

        assert response.status_code == 403

    def test_explicit_workspace_id_narrows_results(self, api_client, workspace_factory, team_factory, user_factory):
        user = user_factory()
        workspace_one = workspace_factory(owner=user)
        workspace_two = workspace_factory(owner=user)
        _add_member(workspace_one, user)
        _add_member(workspace_two, user)
        team_one = team_factory(workspace=workspace_one)
        team_two = team_factory(workspace=workspace_two)
        _make_task(workspace_one, team_one, user, "Patch scanner one")
        _make_task(workspace_two, team_two, user, "Patch scanner two")

        api_client.force_authenticate(user=user)
        response = api_client.get(SUGGEST_URL, {"q": "patch scanner", "workspace_id": str(workspace_one.id)})

        titles = [t["title"] for t in response.data["sections"]["tasks"]]
        assert titles == ["Patch scanner one"]


@pytest.mark.django_db
class TestLimitCap:
    def test_limit_is_capped_at_ten(self, api_client, workspace_factory, team_factory, user_factory):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        _add_member(workspace, user)
        team = team_factory(workspace=workspace)
        for index in range(15):
            _make_task(workspace, team, user, f"Harden endpoint {index}")

        api_client.force_authenticate(user=user)
        response = api_client.get(SUGGEST_URL, {"q": "harden endpoint", "limit": 50})

        assert len(response.data["sections"]["tasks"]) == 10

    def test_default_limit_is_six(self, api_client, workspace_factory, team_factory, user_factory):
        user = user_factory()
        workspace = workspace_factory(owner=user)
        _add_member(workspace, user)
        team = team_factory(workspace=workspace)
        for index in range(9):
            _make_task(workspace, team, user, f"Harden endpoint {index}")

        api_client.force_authenticate(user=user)
        response = api_client.get(SUGGEST_URL, {"q": "harden endpoint"})

        assert len(response.data["sections"]["tasks"]) == 6
