"""Integration tests for ``user_agent`` — workspace member identity surface.

Covers the four production behaviours of UserAgent end-to-end against a real
DB:

* ``list_workspace_members`` returns active members of the current workspace
  only — never leaks across workspaces.
* ``search_workspace_members`` substring-matches on username, email, first,
  and last name and is workspace-scoped (the global ``UserSearch`` REST
  endpoint is admin-only for exactly this reason).
* ``get_user_profile`` resolves a user by UUID or email and returns the
  membership-scoped profile, refusing if the user is not a member of the
  active workspace.
* ``list_user_activity`` reads ``EntityAuditLog`` actor-scoped, and the
  ``@requires_role("owner", "admin")`` gate refuses non-admins.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from django.contrib.contenttypes.models import ContentType

from components.agents.infrastructure.adapters.langchain.agents.user_agent import (
    UserAgent,
)
from components.agents.infrastructure.adapters.langchain.tools import user_agent as user_tools
from infrastructure.persistence.audit.models import EntityAuditLog
from infrastructure.persistence.workspaces.models import WorkspaceMembership


REFUSAL = "You don't have permission to perform this action."


def _actor(user, workspace):
    """The minimal duck-typed stand-in BaseAgent gates + tools read."""
    return SimpleNamespace(
        user_id=str(user.id),
        workspace_id=str(workspace.id),
    )


def _named_user(user_factory, *, email, first_name="", last_name=""):
    """``user_factory`` delegates to ``UserManager.create_user`` which
    doesn't accept ``first_name`` / ``last_name`` kwargs.  This helper
    creates the user then sets the name fields directly so the
    ``user_agent`` tools have something to render.
    """
    user = user_factory(email=email)
    if first_name or last_name:
        user.first_name = first_name
        user.last_name = last_name
        user.save(update_fields=["first_name", "last_name"])
    return user


def _add_member(workspace, user, *, role="member", status=WorkspaceMembership.Status.ACTIVE):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        status=status,
    )


@pytest.mark.django_db
class TestListWorkspaceMembers:
    def test_returns_active_members_with_role_and_email(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        alice = _named_user(user_factory, email="alice@example.com", first_name="Alice")
        bob = _named_user(user_factory, email="bob@example.com", first_name="Bob")
        _add_member(workspace, alice, role="admin")
        _add_member(workspace, bob, role="member")

        agent = _actor(owner, workspace)
        result = user_tools.list_workspace_members(agent, "{}")

        assert "alice@example.com" in result
        assert "bob@example.com" in result
        assert "Role: admin" in result
        assert "Role: member" in result

    def test_does_not_leak_members_from_other_workspaces(
        self, user_factory, workspace_factory
    ):
        owner_a = user_factory()
        workspace_a = workspace_factory(owner=owner_a)
        owner_b = user_factory()
        workspace_b = workspace_factory(owner=owner_b)

        alice = user_factory(email="alice@workspace-a.test")
        bob_b = user_factory(email="bob@workspace-b.test")
        _add_member(workspace_a, alice, role="member")
        _add_member(workspace_b, bob_b, role="member")

        agent = _actor(owner_a, workspace_a)
        result = user_tools.list_workspace_members(agent, "{}")

        assert "alice@workspace-a.test" in result
        assert "bob@workspace-b.test" not in result

    def test_role_filter_narrows_results(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        admin_user = user_factory(email="admin@example.com")
        member_user = user_factory(email="member@example.com")
        _add_member(workspace, admin_user, role="admin")
        _add_member(workspace, member_user, role="member")

        agent = _actor(owner, workspace)
        result = user_tools.list_workspace_members(agent, '{"role": "admin"}')

        assert "admin@example.com" in result
        assert "member@example.com" not in result


@pytest.mark.django_db
class TestSearchWorkspaceMembers:
    def test_substring_matches_name_and_email(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        sarah = _named_user(user_factory, email="sarah@example.com", first_name="Sarah", last_name="Jones")
        _add_member(workspace, sarah, role="member")

        agent = _actor(owner, workspace)
        by_first = user_tools.search_workspace_members(agent, '{"query": "Sarah"}')
        by_email = user_tools.search_workspace_members(agent, '{"query": "sarah@"}')
        no_hit = user_tools.search_workspace_members(agent, '{"query": "zzzzzz"}')

        assert "sarah@example.com" in by_first
        assert "sarah@example.com" in by_email
        assert "No workspace members match" in no_hit

    def test_does_not_leak_other_workspace_members(self, user_factory, workspace_factory):
        owner_a = user_factory()
        workspace_a = workspace_factory(owner=owner_a)
        workspace_b = workspace_factory()
        carol_b = _named_user(user_factory, email="carol@workspace-b.test", first_name="Carol")
        _add_member(workspace_b, carol_b, role="member")

        agent = _actor(owner_a, workspace_a)
        result = user_tools.search_workspace_members(agent, '{"query": "carol"}')

        assert "carol@workspace-b.test" not in result
        assert "No workspace members match" in result

    def test_missing_query_returns_prompt(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _actor(owner, workspace)
        result = user_tools.search_workspace_members(agent, "{}")
        assert "search query" in result.lower()


@pytest.mark.django_db
class TestGetUserProfile:
    def test_lookup_by_email(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        alice = _named_user(user_factory, email="alice@example.com", first_name="Alice")
        _add_member(workspace, alice, role="admin")

        agent = _actor(owner, workspace)
        result = user_tools.get_user_profile(agent, '{"email": "alice@example.com"}')

        assert "alice@example.com" in result
        assert "Role: admin" in result

    def test_lookup_by_user_id(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        alice = user_factory(email="alice@example.com")
        _add_member(workspace, alice, role="member")

        agent = _actor(owner, workspace)
        payload = '{"user_id": "%s"}' % str(alice.id)
        result = user_tools.get_user_profile(agent, payload)

        assert "alice@example.com" in result

    def test_refuses_non_member_lookup(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        stranger = user_factory(email="stranger@elsewhere.test")

        agent = _actor(owner, workspace)
        result = user_tools.get_user_profile(
            agent, '{"email": "stranger@elsewhere.test"}'
        )

        assert "not a member of this workspace" in result

    def test_missing_identifier_returns_prompt(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        agent = _actor(owner, workspace)

        result = user_tools.get_user_profile(agent, "{}")
        assert "user_id" in result.lower() or "email" in result.lower()


@pytest.mark.django_db
class TestListUserActivity:
    def test_returns_actor_scoped_audit_entries(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        editor = user_factory(email="editor@example.com")
        _add_member(workspace, editor, role="member")

        # Seed two audit entries actor'd by `editor`.
        ws_ct = ContentType.objects.get_for_model(type(workspace))
        EntityAuditLog.objects.create(
            workspace=workspace,
            content_type=ws_ct,
            object_id=str(workspace.id),
            field_name="workspace_name",
            previous_value="Old name",
            new_value="New name",
            actor=editor,
        )
        EntityAuditLog.objects.create(
            workspace=workspace,
            content_type=ws_ct,
            object_id=str(workspace.id),
            field_name="status",
            previous_value="draft",
            new_value="active",
            actor=editor,
        )
        # And one actor'd by someone else — must not appear.
        other = user_factory()
        EntityAuditLog.objects.create(
            workspace=workspace,
            content_type=ws_ct,
            object_id=str(workspace.id),
            field_name="privacy",
            previous_value="public",
            new_value="private",
            actor=other,
        )

        agent = _actor(owner, workspace)
        result = user_tools.list_user_activity(
            agent, '{"email": "editor@example.com", "since": "2020-01-01"}'
        )

        assert "workspace_name" in result
        assert "status" in result
        assert "privacy" not in result

    def test_no_entries_returns_empty_notice(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        editor = user_factory(email="quiet@example.com")
        _add_member(workspace, editor, role="member")

        agent = _actor(owner, workspace)
        result = user_tools.list_user_activity(
            agent, '{"email": "quiet@example.com", "since": "2020-01-01"}'
        )
        assert "No audit activity" in result


@pytest.mark.django_db
class TestRoleGateOnListUserActivity:
    """The ``@requires_role("owner", "admin")`` wrapper sits on the class
    method, so we call ``UserAgent.list_user_activity`` directly with a
    ``SimpleNamespace`` actor — that's what the decorator reads.
    """

    def test_owner_passes_without_explicit_membership_row(
        self, user_factory, workspace_factory
    ):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        actor = _actor(owner, workspace)

        result = UserAgent.list_user_activity(actor, "{}")
        assert result != REFUSAL

    def test_admin_passes(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        admin = user_factory()
        _add_member(workspace, admin, role="admin")
        actor = _actor(admin, workspace)

        result = UserAgent.list_user_activity(actor, "{}")
        assert result != REFUSAL

    def test_member_role_refused(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        member = user_factory()
        _add_member(workspace, member, role="member")
        actor = _actor(member, workspace)

        result = UserAgent.list_user_activity(actor, "{}")
        assert result == REFUSAL

    def test_non_member_refused(self, user_factory, workspace_factory):
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        stranger = user_factory()
        actor = _actor(stranger, workspace)

        result = UserAgent.list_user_activity(actor, "{}")
        assert result == REFUSAL


@pytest.mark.django_db
class TestAgentRegistration:
    def test_user_agent_registered_under_canonical_slug_and_aliases(self):
        from components.agents.infrastructure.adapters.langchain.base import (
            AgentRegistry,
        )

        registered = AgentRegistry.list_agents()
        for slug in (
            "user_agent",
            "user",
            "users",
            "identity_agent",
            "identity",
            "members",
        ):
            assert slug in registered, (
                f"user_agent slug/alias '{slug}' missing from registry"
            )

    def test_user_agent_maps_to_identity_domain(self):
        from components.agents.domain.agent_domain_map import resolve_source_domain

        assert resolve_source_domain("user_agent") == "identity"
