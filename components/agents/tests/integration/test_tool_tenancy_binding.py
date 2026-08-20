"""ADR 0031 D1 / Phase 3 — an agent bound to workspace A cannot touch workspace B.

These assert the **effect**, not the shape of a refusal. A tool that returns an
error string while having already written to B is not fixed; a tool that returns
a perfectly ordinary success string describing A while B is untouched is. So
every deny test below reads B's rows before and after and asserts they did not
move, and every read test asserts B's data is *absent from the returned text*
rather than asserting some particular sentence is present.

The other half is just as load-bearing: **a member acting in their own workspace
must still work.** A scope that denies everyone is not a fix, it is an outage
with good intentions. Every deny has an allow beside it.

What these would have caught before Phase 3, per tool:

- ``update_organization`` / ``manage_organization_privacy`` /
  ``manage_organization_tags`` / ``manage_organization_operations`` /
  ``manage_organization_categories`` / ``manage_organization_team`` — five
  writes and a membership mutation, all against whichever workspace the model
  named, via ``_resolve_org_id`` preferring the payload.
- ``get_organization_info`` — resolved by **name** across every workspace row,
  returning another tenant's story, owner username and follower list.
- ``get_organization_followers`` — another tenant's follower usernames and
  **email addresses**.
- ``get_organization_analytics`` — started from ``Workspace.objects.all()``.
- ``check_organization_permissions`` / ``check_project_permissions`` — answered
  truthfully about a workspace the run had no business naming.

``project_agent.check_project_permissions`` gets its own class: it did
``Workspace.objects.get(id=data["workspace_id"])`` with no fallback and no
comparison to the agent's workspace at all.
"""

from __future__ import annotations

import json

import pytest

from components.agents.infrastructure.adapters.langchain.tools import project_agent as project_tools
from components.agents.infrastructure.adapters.langchain.tools import workspace_agent as workspace_tools


class _Agent:
    """The surface the tool bodies read off an agent: the bound tenant and the
    acting user. Nothing else — a real ``BaseAgent`` needs an LLM."""

    def __init__(self, *, workspace_id, user_id=None):
        self.agent_id = "test-agent"
        self.workspace_id = str(workspace_id)
        self.user_id = str(user_id) if user_id else None
        self.config = {}


@pytest.fixture
def tenant_a(workspace_factory, user_factory):
    owner = user_factory(username="owner-a")
    return workspace_factory(owner=owner, workspace_name="Alpha Security Co")


@pytest.fixture
def tenant_b(workspace_factory, user_factory):
    """The victim tenant. Given a follower and an operation so there is
    something concrete to leak or mutate."""
    from infrastructure.persistence.workspaces.models import WorkspaceOperations

    owner = user_factory(username="owner-b")
    member = user_factory(username="member-b")
    workspace = workspace_factory(owner=owner, workspace_name="Bravo Holdings", privacy="private")
    workspace.followers.add(member)
    operation, _ = WorkspaceOperations.objects.get_or_create(name="Bravo secret operation")
    workspace.operations.add(operation)
    workspace.workspace_story = "Bravo's confidential story"
    workspace.save()
    return workspace


@pytest.fixture
def agent_a(tenant_a):
    """An agent legitimately bound to tenant A, acting as A's owner."""
    return _Agent(workspace_id=tenant_a.id, user_id=tenant_a.workspace_owner_id)


def _snapshot(workspace) -> dict:
    workspace.refresh_from_db()
    return {
        "name": workspace.workspace_name,
        "story": workspace.workspace_story,
        "privacy": workspace.privacy,
        "followers": workspace.followers.count(),
        "operations": workspace.operations.count(),
        "tags": workspace.tags.count(),
        "categories": workspace.workspace_categories.count(),
    }


@pytest.mark.django_db
class TestCrossTenantWritesAreImpossible:
    """Row counts and field values, before and after. Not status codes."""

    def test_update_organization_cannot_rename_another_tenant(self, agent_a, tenant_a, tenant_b):
        before = _snapshot(tenant_b)

        workspace_tools.update_organization(
            agent_a,
            {"organization_id": str(tenant_b.id), "field": "workspace_name", "new_value": "PWNED"},
        )

        assert _snapshot(tenant_b) == before, "workspace B was mutated by an agent bound to workspace A"
        tenant_a.refresh_from_db()
        assert tenant_a.workspace_name == "PWNED", (
            "the write must still land — on the BOUND workspace. If this fails the "
            "fix denied everyone rather than binding the tenant."
        )

    def test_manage_privacy_cannot_expose_another_tenant(self, agent_a, tenant_a, tenant_b):
        assert tenant_b.privacy == "private"
        before = _snapshot(tenant_b)

        workspace_tools.manage_organization_privacy(
            agent_a,
            {"organization_id": str(tenant_b.id), "privacy_level": "public"},
        )

        assert _snapshot(tenant_b) == before
        tenant_a.refresh_from_db()
        assert tenant_a.privacy == "public", "the bound workspace's privacy must still be settable"

    def test_manage_tags_cannot_write_into_another_tenants_vocabulary(self, agent_a, tenant_a, tenant_b):
        before = _snapshot(tenant_b)

        workspace_tools.manage_organization_tags(
            agent_a,
            {"organization_id": str(tenant_b.id), "action": "add", "tags": ["injected"]},
        )

        assert _snapshot(tenant_b)["tags"] == before["tags"]
        tenant_a.refresh_from_db()
        assert tenant_a.tags.count() == 1, "tagging the bound workspace must still work"

    def test_manage_operations_cannot_edit_another_tenants_operations(self, agent_a, tenant_a, tenant_b):
        before = _snapshot(tenant_b)

        workspace_tools.manage_organization_operations(
            agent_a,
            {"organization_id": str(tenant_b.id), "action": "add", "operations": ["injected op"]},
        )

        assert _snapshot(tenant_b)["operations"] == before["operations"]
        tenant_a.refresh_from_db()
        assert tenant_a.operations.count() == 1

    def test_manage_categories_cannot_edit_another_tenants_categories(self, agent_a, tenant_a, tenant_b):
        before = _snapshot(tenant_b)

        workspace_tools.manage_organization_categories(
            agent_a,
            {"organization_id": str(tenant_b.id), "categories": ["Injected"]},
        )

        assert _snapshot(tenant_b)["categories"] == before["categories"]
        tenant_a.refresh_from_db()
        assert tenant_a.workspace_categories.filter(name="Injected").exists()

    def test_manage_team_cannot_add_a_member_to_another_tenant(self, agent_a, tenant_a, tenant_b, user_factory):
        outsider = user_factory(username="outsider")
        before = _snapshot(tenant_b)

        workspace_tools.manage_organization_team(
            agent_a,
            {"organization_id": str(tenant_b.id), "action": "add", "user_id": str(outsider.id)},
        )

        assert _snapshot(tenant_b)["followers"] == before["followers"], (
            "an agent bound to A granted membership of B — the sharpest form of this bug"
        )
        tenant_a.refresh_from_db()
        assert tenant_a.followers.filter(id=outsider.id).exists(), (
            "adding a member to the bound workspace must still work"
        )

    def test_manage_team_can_still_remove_from_the_bound_workspace(self, agent_a, tenant_a, user_factory):
        member = user_factory(username="member-a")
        tenant_a.followers.add(member)

        result = workspace_tools.manage_organization_team(
            agent_a,
            {"action": "remove", "user_id": str(member.id)},
        )

        tenant_a.refresh_from_db()
        assert not tenant_a.followers.filter(id=member.id).exists()
        assert "Removed" in result


@pytest.mark.django_db
class TestCrossTenantReadsAreImpossible:
    """The leak side. Assert B's data is absent from the text the model reads."""

    def test_get_organization_info_by_id_describes_the_bound_workspace(self, agent_a, tenant_a, tenant_b):
        result = workspace_tools.get_organization_info(agent_a, {"organization_id": str(tenant_b.id)})

        assert tenant_a.workspace_name in result
        assert "Bravo Holdings" not in result
        assert "Bravo's confidential story" not in result
        assert "owner-b" not in result

    def test_get_organization_info_by_name_is_not_a_lookup_oracle(self, agent_a, tenant_a, tenant_b):
        """The pre-Phase-3 body did ``workspace_name__iexact`` then
        ``__icontains`` across every row, so naming another tenant returned it —
        and naming a *guess* told you whether it existed."""
        result = workspace_tools.get_organization_info(agent_a, "Bravo Holdings")

        assert "Bravo Holdings" not in result
        assert tenant_a.workspace_name in result

    def test_get_organization_followers_does_not_leak_another_tenants_emails(self, agent_a, tenant_a, tenant_b):
        member_email = tenant_b.followers.first().email

        result = workspace_tools.get_organization_followers(agent_a, {"organization_id": str(tenant_b.id)})

        assert member_email not in result
        assert "member-b" not in result

    def test_get_organization_followers_still_lists_the_bound_workspaces_own(self, agent_a, tenant_a, user_factory):
        member = user_factory(username="member-a")
        tenant_a.followers.add(member)

        result = workspace_tools.get_organization_followers(agent_a)

        assert "member-a" in result, "the legitimate read must still work"

    def test_get_organization_operations_does_not_leak_another_tenants(self, agent_a, tenant_a, tenant_b):
        result = workspace_tools.get_organization_operations(agent_a, {"organization_id": str(tenant_b.id)})

        assert "Bravo secret operation" not in result

    def test_get_organization_operations_still_lists_the_bound_workspaces_own(self, agent_a, tenant_a):
        from infrastructure.persistence.workspaces.models import WorkspaceOperations

        operation, _ = WorkspaceOperations.objects.get_or_create(name="Alpha's own operation")
        tenant_a.operations.add(operation)

        result = workspace_tools.get_organization_operations(agent_a)

        assert "Alpha's own operation" in result

    def test_analytics_counts_only_the_bound_workspace(self, agent_a, tenant_a, tenant_b, user_factory):
        """It used to start from ``Workspace.objects.all()``. With two tenants
        in the database the old body reported 2 — a count of other people's
        organizations, and follower totals aggregated across them."""
        tenant_b.followers.add(user_factory(username="another-b-follower"))

        # Names B explicitly. With an empty payload the old body also landed on
        # A (the fallback), so an empty payload would prove nothing — this is the
        # call the model would actually make after reading the old description.
        result = workspace_tools.get_organization_analytics(agent_a, {"organization_id": str(tenant_b.id)})

        assert "Total Organizations: 1" in result
        assert "Total Followers: 0" in result, (
            "tenant B has followers and tenant A has none; any non-zero total is B's data"
        )

    def test_analytics_still_reflects_the_bound_workspaces_own_followers(self, agent_a, tenant_a, user_factory):
        tenant_a.followers.add(user_factory(username="a-follower"))

        result = workspace_tools.get_organization_analytics(agent_a, {})

        assert "Total Organizations: 1" in result
        assert "Total Followers: 1" in result

    def test_check_organization_permissions_answers_about_the_bound_workspace(self, agent_a, tenant_a, tenant_b):
        """B's owner is nobody in A. Asking about B while bound to A used to
        return "full organization access (organization owner)" — true of B, and
        a membership disclosure."""
        b_owner_id = str(tenant_b.workspace_owner_id)

        result = workspace_tools.check_organization_permissions(
            agent_a,
            {"organization_id": str(tenant_b.id), "user_id": b_owner_id},
        )

        assert "owner" not in result.lower()
        assert "Bravo Holdings" not in result

    def test_check_organization_permissions_still_recognises_the_bound_owner(self, agent_a, tenant_a):
        result = workspace_tools.check_organization_permissions(
            agent_a,
            {"user_id": str(tenant_a.workspace_owner_id)},
        )

        assert "owner" in result.lower(), "the legitimate permission answer must still work"


@pytest.mark.django_db
class TestCheckProjectPermissionsBindsToTheRun:
    """The entry ADR 0031 did not anticipate: no fallback, no comparison, just
    ``Workspace.objects.get(id=data["workspace_id"])``."""

    def test_naming_another_workspace_does_not_answer_about_it(self, tenant_a, tenant_b):
        agent = _Agent(workspace_id=tenant_a.id, user_id=tenant_b.workspace_owner_id)

        result = project_tools.check_project_permissions(
            agent,
            {"workspace_id": str(tenant_b.id), "user_id": str(tenant_b.workspace_owner_id)},
        )

        assert "workspace owner" not in result.lower(), "B's owner was told they own something, by a run bound to A"
        assert "does not have project access" in result.lower()

    def test_the_bound_workspaces_owner_is_still_recognised(self, tenant_a):
        owner_id = str(tenant_a.workspace_owner_id)
        agent = _Agent(workspace_id=tenant_a.id, user_id=owner_id)

        result = project_tools.check_project_permissions(agent, {"user_id": owner_id})

        assert "workspace owner" in result.lower()

    def test_a_bound_team_member_is_still_recognised(self, tenant_a, user_factory, team_factory):
        member = user_factory(username="team-member-a")
        team_factory(workspace=tenant_a, created_by=tenant_a.workspace_owner, members=[member])
        agent = _Agent(workspace_id=tenant_a.id, user_id=member.id)

        result = project_tools.check_project_permissions(agent, {"user_id": str(member.id)})

        assert "member of team" in result.lower()

    def test_an_unbound_run_refuses_rather_than_crashing(self, tenant_b):
        agent = _Agent(workspace_id="", user_id=tenant_b.workspace_owner_id)

        result = project_tools.check_project_permissions(
            agent,
            {"workspace_id": str(tenant_b.id), "user_id": str(tenant_b.workspace_owner_id)},
        )

        assert "not bound to a workspace" in result
        assert "Error checking permissions" not in result, "a missing binding is a refusal, not a traceback"


@pytest.mark.django_db
class TestTheFrameworkStripsTheKeyBeforeTheBodyRuns:
    """The by-construction half. The bodies above read the run's workspace and
    would be correct even if handed a tenancy key; these prove the key does not
    reach them in the first place, on the path the model actually uses.

    Exercised through the promoted ``StructuredTool`` — i.e. through
    ``_tenancy_scoped`` — rather than by calling the wrapper directly, so what is
    asserted is the wiring, not the helper.
    """

    @staticmethod
    def _promoted(agent, tool_name):
        from components.agents.infrastructure.adapters.langchain.agents.workspace_agent import WorkspaceAgent

        for method_name, meta in WorkspaceAgent._decorated_tools:
            if (meta.get("name") or method_name) == tool_name:
                return method_name, meta
        raise AssertionError(f"{tool_name} is not a registered tool")

    def test_promoted_tool_drops_a_model_supplied_workspace_id(self, agent_a, tenant_a, tenant_b):
        from components.agents.infrastructure.adapters.langchain.base import _tenancy_scoped

        method_name, meta = self._promoted(agent_a, "update_organization")
        bound = workspace_tools.update_organization
        guarded = _tenancy_scoped(lambda payload: bound(agent_a, payload), "update_organization", agent_a)

        before = _snapshot(tenant_b)
        guarded(
            json.dumps({"organization_id": str(tenant_b.id), "field": "workspace_name", "new_value": "PWNED VIA JSON"})
        )

        assert _snapshot(tenant_b) == before
        tenant_a.refresh_from_db()
        assert tenant_a.workspace_name == "PWNED VIA JSON", "the rest of the payload must survive the scrub"
        assert meta.get("spec").scope == "workspace_bound", (
            f"{method_name} must declare its tenancy binding (ADR 0031 D1)"
        )

    def test_the_scrub_removes_every_tenancy_alias_and_keeps_the_rest(self):
        from components.agents.application.policies.tool_tenancy import scrub_tenancy_keys

        payload = {
            "workspace_id": "x",
            "organization_id": "x",
            "org_id": "x",
            "tenant_id": "x",
            "workspace": "x",
            "organization": "x",
            "field": "workspace_name",
            "new_value": "keep me",
        }
        scrubbed, removed = scrub_tenancy_keys(payload)

        assert scrubbed == {"field": "workspace_name", "new_value": "keep me"}
        assert set(removed) == {
            "workspace_id",
            "organization_id",
            "org_id",
            "tenant_id",
            "workspace",
            "organization",
        }

    def test_the_scrub_reaches_into_a_json_encoded_payload(self):
        from components.agents.application.policies.tool_tenancy import scrub_tenancy_keys

        scrubbed, removed = scrub_tenancy_keys(json.dumps({"organization_id": "x", "field": "y"}))

        assert json.loads(scrubbed) == {"field": "y"}
        assert removed == ("organization_id",)

    def test_the_scrub_leaves_a_plain_string_alone(self):
        from components.agents.application.policies.tool_tenancy import scrub_tenancy_keys

        assert scrub_tenancy_keys("mission and story") == ("mission and story", ())
        assert scrub_tenancy_keys(None) == (None, ())
        assert scrub_tenancy_keys("{not json") == ("{not json", ())

    def test_the_middleware_strips_the_key_for_every_tool_however_registered(self, agent_a, tenant_b):
        """The seam the promotion loop cannot cover — middleware wraps the
        ``ToolNode``, so a tool built outside the loop is still guarded."""
        from components.agents.infrastructure.adapters.langchain.middleware.tool_governance import (
            ToolGovernanceMiddleware,
        )

        seen: dict = {}

        class _Request:
            def __init__(self, tool_call):
                self.tool_call = tool_call

            def override(self, **overrides):
                return _Request(overrides["tool_call"])

        middleware = ToolGovernanceMiddleware(agent=agent_a)

        def handler(request):
            seen["args"] = request.tool_call["args"]
            return "ok"

        middleware.wrap_tool_call(
            _Request(
                {
                    "name": "update_organization",
                    "id": "call-1",
                    "args": {"workspace_id": str(tenant_b.id), "field": "x"},
                }
            ),
            handler,
        )

        assert seen["args"] == {"field": "x"}, "the middleware must not pass a model-supplied tenant through"
