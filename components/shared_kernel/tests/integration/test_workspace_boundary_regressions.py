"""Three workspace-boundary holes, each asserted from the outside.

Every endpoint below took the target workspace from CALLER-CONTROLLED input —
a query parameter or a request body — rather than from the URL, so no
URL-scoped permission class was in a position to guard it. That is the shared
root cause; the three fixes differ only in what the right answer was.

The shape of each test is the same and deliberately blunt: build two fully
independent workspaces, act as a member of A (or as nobody at all), and assert
B's data is neither readable nor writable. Both directions are asserted — the
outsider is denied AND the legitimate caller still succeeds. A test that only
proved "403 for the outsider" would still pass if the endpoint were broken for
everyone, which is how a security fix quietly becomes an outage.

Companion to ``components/findings/tests/integration/test_cross_tenant_isolation.py``,
which covers the read surfaces that were already scoped.
"""

from __future__ import annotations

import pytest
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from rest_framework.test import APIClient

from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _member(workspace, user, *, role="member"):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        persona="contributor",
        status=WorkspaceMembership.Status.ACTIVE,
    )


@pytest.fixture
def two_tenants(workspace_factory, user_factory):
    """Two independent workspaces. ``alice`` is in A only, ``bob`` in B only."""
    alice = user_factory()
    bob = user_factory()
    ws_a = workspace_factory(owner=user_factory())
    ws_b = workspace_factory(owner=user_factory())
    _member(ws_a, alice, role="admin")
    _member(ws_b, bob, role="admin")
    return {"alice": alice, "bob": bob, "ws_a": ws_a, "ws_b": ws_b}


def _as(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ── 1. GET /ai/agents/graph/?workspace_id= ──────────────────────────────────


class TestAgentGraphIsolation:
    """The workspace arrives as a QUERY PARAM, so IsAuthenticated proved only
    that the caller was *someone* — not that the workspace was theirs."""

    @property
    def url(self) -> str:
        # Resolved, never hardcoded: the route is mounted unversioned at the
        # root AND under /api/v0|v1/, and a literal would silently 404 into a
        # false pass.
        return reverse("agents:agent-graph")

    def test_member_of_a_cannot_read_bs_agent_graph(self, two_tenants):
        response = _as(two_tenants["alice"]).get(self.url, {"workspace_id": str(two_tenants["ws_b"].id)})
        assert response.status_code == 403

    def test_member_still_reads_their_own_agent_graph(self, two_tenants):
        response = _as(two_tenants["alice"]).get(self.url, {"workspace_id": str(two_tenants["ws_a"].id)})
        assert response.status_code == 200

    def test_anonymous_is_rejected(self, two_tenants):
        response = APIClient().get(self.url, {"workspace_id": str(two_tenants["ws_a"].id)})
        assert response.status_code in (401, 403)

    def test_owner_without_a_membership_row_is_not_locked_out(self, workspace_factory, user_factory):
        """An owner passes even with no WorkspaceMembership row.

        ``ensure_membership`` writes that row at creation time today, but
        ``backfill_memberships`` exists because older workspaces do not have
        it. Without the owner clause this fix would lock those owners out of
        their own data — trading a leak for an outage. This is the test that
        caught it: the pre-existing ``test_agents_graph`` fixture builds
        exactly such a workspace.
        """
        owner = user_factory()
        workspace = workspace_factory(owner=owner)
        assert not WorkspaceMembership.objects.filter(workspace=workspace, user=owner).exists()

        response = _as(owner).get(self.url, {"workspace_id": str(workspace.id)})
        assert response.status_code == 200


# ── 2. POST /workspaces/assign-contribution-means/ ──────────────────────────


class TestContributionMeansAssignmentIsolation:
    """The workspace arrives in the request BODY, so the permission class —
    which granted anything short of anonymous — never saw which workspace was
    being written. Any authenticated user of any tenant could rewrite any
    other workspace's contribution means by naming its UUID."""

    @property
    def url(self) -> str:
        return reverse("assign-contribution-means")

    def test_anonymous_cannot_rewrite_a_workspaces_contribution_means(self, two_tenants):
        # This one ALREADY passed before the fix — the authentication layer
        # refuses anonymous callers 401 regardless of the permission class.
        # Kept as a standing guard, not as evidence of the fix: the
        # cross-tenant test below is what actually failed beforehand.
        response = APIClient().post(
            self.url,
            {"workspace": str(two_tenants["ws_b"].id), "means": []},
            format="json",
        )
        assert response.status_code in (401, 403), "an anonymous caller must never write another tenant's config"

    def test_member_of_a_cannot_rewrite_bs_contribution_means(self, two_tenants):
        response = _as(two_tenants["alice"]).post(
            self.url,
            {"workspace": str(two_tenants["ws_b"].id), "means": []},
            format="json",
        )
        assert response.status_code == 403

    def test_admin_of_a_can_still_write_their_own(self, two_tenants):
        response = _as(two_tenants["alice"]).post(
            self.url,
            {"workspace": str(two_tenants["ws_a"].id), "means": []},
            format="json",
        )
        assert response.status_code == 200, "the legitimate admin path must keep working"


# ── 3. POST /identity/invitations/ (deleted) ────────────────────────────────


class TestIdentityInvitationsRouteIsGone:
    """Deleted rather than gated: an unauthenticated enumeration oracle with
    no client. Asserting on the ROUTE, not a status code, so the test fails if
    anyone re-registers it — a 403 would look like a pass while the surface
    was back."""

    def test_route_is_not_registered(self):
        with pytest.raises(NoReverseMatch):
            reverse("user-invitation-detail")

    def test_path_no_longer_resolves(self):
        # resolve(), not a status-code assertion. Posting a bogus user id to
        # the live endpoint returned 404 ("User not found") — so a
        # status-code test would have passed BEFORE the fix too, for entirely
        # the wrong reason, and proved nothing.
        with pytest.raises(Resolver404):
            resolve("/identity/invitations/")
