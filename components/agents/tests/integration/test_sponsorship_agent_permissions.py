"""Permission gating tests for sponsorship_agent (Action List #5).

The sponsorship agent owns the most sensitive workspace surface — donor PII,
recipient stories, financial commitments, and external sponsor emails. Before
this PR, none of its 20 tools had ``@requires_role`` gates: a viewer could
fire ``cancel_sponsorship`` or ``manage_sponsorship_payments`` through the
deep planner and the only thing stopping it was that the LLM wasn't likely
to try.

This module locks in the audit decision (per ADR 0002 — role-only, never
persona):

* **Read-only tools** stay ungated (list_recipients, list_sponsors,
  get_*_info, get_sponsorship_overview, get_sponsorship_analytics,
  generate_sponsorship_report). Viewers can browse.
* **Day-to-day write tools** require owner / admin / member
  (create_*, update_*, manage_sponsorship_goal, send_sponsor_update).
* **Financial-state tools** require owner / admin only
  (update_sponsorship_status, cancel_sponsorship, manage_sponsorship_payments).
* **Owners always pass** even without an explicit membership row — the
  decorator's ``workspace_owner_id`` short-circuit.

Tests call the agent-class bound methods directly (the ``@requires_role``
wrapper sits on the class method, not on the underlying tool function).
A ``SimpleNamespace`` stand-in with ``user_id`` + ``workspace_id`` is
sufficient — that's all the wrapper reads. Positive assertions verify
``result != REFUSAL``; we don't care what the underlying tool body returns,
only that the gate didn't refuse.
"""
from types import SimpleNamespace

import pytest

from components.agents.infrastructure.adapters.langchain.agents.sponsorship_agent import (
    SponsorshipAgent,
)
from infrastructure.persistence.workspaces.models import WorkspaceMembership


REFUSAL = "You don't have permission to perform this action."


@pytest.fixture
def actor_for(user_factory, workspace_factory):
    """Build a ``SimpleNamespace`` actor with ``user_id`` + ``workspace_id``.

    Skips ``BaseAgent`` init (LLM, memory, telemetry) since the gate only
    needs the two ID attrs.
    """

    def _build(*, role=None, owner=False):
        owner_user = user_factory()
        workspace = workspace_factory(owner=owner_user)
        if owner:
            actor = owner_user
        else:
            actor = user_factory()
            if role is not None:
                WorkspaceMembership.objects.create(
                    workspace=workspace,
                    user=actor,
                    role=role,
                    status=WorkspaceMembership.Status.ACTIVE,
                )
        return SimpleNamespace(
            user_id=str(actor.id),
            workspace_id=str(workspace.id),
        )

    return _build


@pytest.mark.django_db
class TestMemberTierTools:
    """Tools gated as ``@requires_role("owner", "admin", "member")``.

    These are the day-to-day data-management tools — creating recipient
    profiles, editing stories, sending sponsor updates. Members can do
    them; viewers cannot.
    """

    @pytest.mark.parametrize(
        "tool_name",
        [
            "create_child_profile",
            "create_sponsor_profile",
            "create_sponsorship",
            "update_child_progress",
            "update_recipient",
            "update_sponsor",
            "manage_sponsorship_goal",
            "send_sponsor_update",
        ],
    )
    def test_member_role_passes_gate(self, actor_for, tool_name):
        actor = actor_for(role="member")
        method = getattr(SponsorshipAgent, tool_name)
        assert method(actor, "{}") != REFUSAL

    @pytest.mark.parametrize(
        "tool_name",
        [
            "create_child_profile",
            "create_sponsor_profile",
            "create_sponsorship",
            "update_child_progress",
            "update_recipient",
            "update_sponsor",
            "manage_sponsorship_goal",
            "send_sponsor_update",
        ],
    )
    def test_viewer_role_refused(self, actor_for, tool_name):
        actor = actor_for(role="viewer")
        method = getattr(SponsorshipAgent, tool_name)
        assert method(actor, "{}") == REFUSAL


@pytest.mark.django_db
class TestAdminTierTools:
    """Tools gated as ``@requires_role("owner", "admin")``.

    These move financial state — payment_status, cancellation, billing.
    Members are explicitly refused; only owner / admin proceed.
    """

    @pytest.mark.parametrize(
        "tool_name",
        [
            "update_sponsorship_status",
            "cancel_sponsorship",
            "manage_sponsorship_payments",
        ],
    )
    def test_admin_role_passes_gate(self, actor_for, tool_name):
        actor = actor_for(role="admin")
        method = getattr(SponsorshipAgent, tool_name)
        assert method(actor, "{}") != REFUSAL

    @pytest.mark.parametrize(
        "tool_name",
        [
            "update_sponsorship_status",
            "cancel_sponsorship",
            "manage_sponsorship_payments",
        ],
    )
    def test_member_role_refused(self, actor_for, tool_name):
        actor = actor_for(role="member")
        method = getattr(SponsorshipAgent, tool_name)
        assert method(actor, "{}") == REFUSAL

    @pytest.mark.parametrize(
        "tool_name",
        [
            "update_sponsorship_status",
            "cancel_sponsorship",
            "manage_sponsorship_payments",
        ],
    )
    def test_viewer_role_refused(self, actor_for, tool_name):
        actor = actor_for(role="viewer")
        method = getattr(SponsorshipAgent, tool_name)
        assert method(actor, "{}") == REFUSAL


@pytest.mark.django_db
class TestOwnerShortCircuit:
    """Owner-of-workspace always passes — no membership row required.

    The decorator's ``workspace_owner_id`` check fires before the
    membership lookup, so owners can run admin-tier tools immediately
    after creating a workspace.
    """

    @pytest.mark.parametrize(
        "tool_name",
        [
            "create_sponsorship",
            "cancel_sponsorship",
            "manage_sponsorship_payments",
            "update_sponsorship_status",
        ],
    )
    def test_owner_passes_without_membership_row(self, actor_for, tool_name):
        actor = actor_for(owner=True)
        method = getattr(SponsorshipAgent, tool_name)
        assert method(actor, "{}") != REFUSAL


@pytest.mark.django_db
class TestReadOnlyToolsUngated:
    """Read-only tools have no ``@requires_role`` — viewers can browse.

    If someone retroactively adds a gate to a read-only tool the LLM
    would silently fail "as viewer" without a recovery path.
    """

    @pytest.mark.parametrize(
        "tool_name",
        [
            "list_recipients",
            "list_sponsors",
            "get_child_info",
            "get_sponsor_info",
            "get_sponsorship_status",
            "get_sponsorship_analytics",
            "get_sponsorship_overview",
            "check_sponsorship_permissions",
        ],
    )
    def test_viewer_role_passes_read_only(self, actor_for, tool_name):
        actor = actor_for(role="viewer")
        method = getattr(SponsorshipAgent, tool_name)
        assert method(actor, "{}") != REFUSAL


@pytest.mark.django_db
class TestMissingContext:
    """Missing user_id or workspace_id → refusal (defensive default).

    Prevents an agent with broken init from accidentally running a
    write tool with no actor.
    """

    def test_no_user_id_refused(self):
        actor = SimpleNamespace(user_id=None, workspace_id="some-id")
        assert SponsorshipAgent.cancel_sponsorship(actor, "{}") == REFUSAL

    def test_no_workspace_id_refused(self):
        actor = SimpleNamespace(user_id="some-id", workspace_id=None)
        assert SponsorshipAgent.cancel_sponsorship(actor, "{}") == REFUSAL
