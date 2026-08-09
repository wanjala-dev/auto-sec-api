"""Cross-tenant isolation — the assertion this product cannot afford to get wrong.

Auto-Sec is multi-tenant and holds customers' findings, cloud asset graphs, scan
history, and log-derived detections. "Workspace A can never read workspace B's
security data" is the single most consequential invariant in the system: a leak
here is not a bug report, it is an incident involving somebody else's
vulnerabilities.

Every read path IS tenant-scoped today — but through convention (each controller
calls ``is_workspace_member`` and each query filters on ``workspace_id``), not
through anything that fails loudly when someone adds the next endpoint and
forgets. These tests make the convention enforceable, across the security read
surfaces an attacker would actually want:

  * findings (the unified SSOT — ADR 0004)
  * finding detail (the deep-link read behind Slack alerts)
  * ATT&CK coverage + compliance summary (aggregate reads over findings)
  * the cloud asset graph (inventory + attack paths)
  * code-security repos + scan snapshots

The shape of every test is the same and deliberately blunt: build TWO fully
independent workspaces with real data in each, authenticate as a member of A,
and assert that B's data is neither readable nor even acknowledged.

Both directions are asserted — the outsider is denied AND the legitimate member
still gets their own data. A test that only proves "403 for the outsider" would
still pass if the endpoint were broken for everyone.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


# ── fixtures ────────────────────────────────────────────────────────────────


def _member(workspace, user, *, role="member"):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        persona="contributor",
        status=WorkspaceMembership.Status.ACTIVE,
    )


def _finding(workspace, *, title: str, severity: str = "high", source: str = "cloud_posture") -> Finding:
    now = datetime.now(UTC)
    return Finding.objects.create(
        workspace=workspace,
        source=source,
        fingerprint=f"fp-{uuid.uuid4()}",
        asset_urn=f"urn:aws:s3:::{uuid.uuid4()}",
        severity=severity,
        status="open",
        title=title,
        description="secret detail that must never cross a tenant boundary",
        first_seen_at=now,
        last_seen_at=now,
    )


@pytest.fixture
def two_tenants(workspace_factory, user_factory):
    """Two independent workspaces, each with its own member and its own finding.

    ``alice`` belongs ONLY to workspace A; ``bob`` ONLY to workspace B.
    """
    alice = user_factory()
    bob = user_factory()
    ws_a = workspace_factory(owner=user_factory())
    ws_b = workspace_factory(owner=user_factory())
    _member(ws_a, alice)
    _member(ws_b, bob)
    finding_a = _finding(ws_a, title="[A] public S3 bucket")
    finding_b = _finding(ws_b, title="[B] exposed RDS instance")
    return {
        "alice": alice,
        "bob": bob,
        "ws_a": ws_a,
        "ws_b": ws_b,
        "finding_a": finding_a,
        "finding_b": finding_b,
    }


def _as(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# ── findings SSOT ───────────────────────────────────────────────────────────


class TestFindingListIsolation:
    def test_member_of_a_cannot_list_bs_findings(self, two_tenants):
        url = reverse("findings-list", kwargs={"workspace_id": two_tenants["ws_b"].id})

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 403, "a non-member listed another tenant's findings — cross-tenant leak"

    def test_member_of_a_still_sees_their_own_findings(self, two_tenants):
        """The control: isolation must not be achieved by breaking the endpoint."""
        url = reverse("findings-list", kwargs={"workspace_id": two_tenants["ws_a"].id})

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 200, response.data
        titles = [row["title"] for row in response.data["data"]["items"]]
        assert "[A] public S3 bucket" in titles
        assert "[B] exposed RDS instance" not in titles

    def test_own_workspace_listing_never_contains_another_tenants_rows(self, two_tenants):
        """Even with both tenants holding findings, the query is scoped."""
        url = reverse("findings-list", kwargs={"workspace_id": two_tenants["ws_a"].id})

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 200
        returned_ids = {row["id"] for row in response.data["data"]["items"]}
        assert str(two_tenants["finding_b"].id) not in returned_ids


class TestFindingDetailIsolation:
    def test_cannot_read_another_tenants_finding_by_id(self, two_tenants):
        """The deep-link read: knowing a finding's UUID must not be enough."""
        url = reverse(
            "findings-detail",
            kwargs={
                "workspace_id": two_tenants["ws_b"].id,
                "finding_id": two_tenants["finding_b"].id,
            },
        )

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 403

    def test_cannot_smuggle_another_tenants_finding_through_own_workspace(self, two_tenants):
        """The nastier variant: a workspace id you legitimately hold, paired with
        a finding id you do not. Must 404 — never serve B's row under A's scope."""
        url = reverse(
            "findings-detail",
            kwargs={
                "workspace_id": two_tenants["ws_a"].id,
                "finding_id": two_tenants["finding_b"].id,
            },
        )

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 404, (
            "another tenant's finding was served under a workspace the caller does hold "
            "— the workspace_id in the URL is not being used to scope the lookup"
        )


class TestFindingMutationIsolation:
    def test_cannot_change_status_of_another_tenants_finding(self, two_tenants):
        url = reverse(
            "findings-status",
            kwargs={
                "workspace_id": two_tenants["ws_b"].id,
                "finding_id": two_tenants["finding_b"].id,
            },
        )

        response = _as(two_tenants["alice"]).post(url, {"action": "resolve"}, format="json")

        assert response.status_code in (403, 404), response.status_code
        two_tenants["finding_b"].refresh_from_db()
        assert two_tenants["finding_b"].status == "open", "a non-member mutated another tenant's finding"


class TestFindingAggregateIsolation:
    """Aggregates are an easy place to leak: they summarise rather than list, so a
    missing scope shows up as a number rather than a visible row."""

    @pytest.mark.parametrize(
        "route",
        ["findings-attck-coverage", "findings-compliance-summary"],
    )
    def test_aggregates_reject_non_members(self, two_tenants, route):
        url = reverse(route, kwargs={"workspace_id": two_tenants["ws_b"].id})

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 403


# ── cloud asset graph ───────────────────────────────────────────────────────


class TestCloudGraphIsolation:
    def test_cannot_read_another_tenants_asset_graph(self, two_tenants):
        url = reverse(
            "cloud-graph-asset-graph",
            kwargs={"workspace_id": two_tenants["ws_b"].id},
        )

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 403

    def test_member_can_read_their_own_asset_graph(self, two_tenants):
        """Control — proves the 403 above is the membership gate, not a broken route."""
        url = reverse(
            "cloud-graph-asset-graph",
            kwargs={"workspace_id": two_tenants["ws_a"].id},
        )

        response = _as(two_tenants["alice"]).get(url)

        assert response.status_code == 200, response.data


# ── code security ───────────────────────────────────────────────────────────


@pytest.fixture
def code_security_enabled(two_tenants):
    """Turn feature.code_security ON for BOTH workspaces.

    Load-bearing for the tests below, not scenery: the code-security gate
    returns 403 for a non-member AND 403 for a disabled feature. Without the
    flag on, an isolation assertion would pass because the feature is off —
    i.e. it would keep passing even if the membership check were deleted. With
    the flag on for both tenants, the only thing that can produce a 403 is the
    membership gate, and the member-side control below proves it.
    """
    from components.shared_platform.infrastructure.services.feature_flags import (
        bump_feature_flags_version,
    )
    from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule

    flag, _ = FeatureFlag.objects.get_or_create(key="feature.code_security", defaults={"default_enabled": False})
    for workspace in (two_tenants["ws_a"], two_tenants["ws_b"]):
        FeatureFlagRule.objects.get_or_create(
            flag=flag,
            scope=FeatureFlagRule.Scope.WORKSPACE,
            workspace=workspace,
            defaults={"enabled": True},
        )
    bump_feature_flags_version()
    return two_tenants


class TestCodeSecurityIsolation:
    @pytest.mark.parametrize("route", ["code-security-repos", "code-security-snapshots"])
    def test_cannot_read_another_tenants_code_security_data(self, code_security_enabled, route):
        url = reverse(route, kwargs={"workspace_id": code_security_enabled["ws_b"].id})

        response = _as(code_security_enabled["alice"]).get(url)

        assert response.status_code == 403, response.status_code

    @pytest.mark.parametrize("route", ["code-security-repos", "code-security-snapshots"])
    def test_member_can_read_their_own_code_security_data(self, code_security_enabled, route):
        """Control — proves the 403 above comes from the membership gate and not
        from the feature flag (the same gate returns 403 for both)."""
        url = reverse(route, kwargs={"workspace_id": code_security_enabled["ws_a"].id})

        response = _as(code_security_enabled["alice"]).get(url)

        assert response.status_code == 200, response.data


# ── an authenticated user with NO workspaces at all ─────────────────────────


class TestUnaffiliatedUserIsolation:
    def test_user_with_no_memberships_reads_nothing(self, two_tenants, user_factory):
        """A freshly registered account — the cheapest attack to attempt."""
        stranger = user_factory()
        client = _as(stranger)

        for workspace in (two_tenants["ws_a"], two_tenants["ws_b"]):
            response = client.get(reverse("findings-list", kwargs={"workspace_id": workspace.id}))
            assert response.status_code == 403
