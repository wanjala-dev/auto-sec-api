"""Backbone RBAC matrix — org built through the REAL invite endpoints, then
ALLOW **and** DENY asserted per capability for every seeded role.

The org is not fixture-fabricated: the owner drives ``POST
/membership/invitations/persona/`` and each member joins through ``POST
/membership/invitations/persona/accept/`` (the magic link), exactly like a
customer walk. The matrix then pins what each RBAC tier can and cannot do on
the backbone surfaces.

The REAL permission-per-endpoint contract (grounded in the controllers — this
suite pins it so it can never silently drift):

======================================================  =============================================
Endpoint                                                Gate
======================================================  =============================================
GET  /findings/workspaces/<ws>/                         active membership (any role)
POST /findings/…/<finding>/status/                      active membership (any role — documented:
                                                        "matching the read gate")
POST /findings/…/<finding>/tags/                        active membership (any role)
POST /findings/…/sample-data/mode/                      workspace OWNER only
GET/POST /tagging/…/tags/                               active membership (any role)
PATCH/DELETE /tagging/…/tags/<id>/                      role in (owner, admin)
ALL  /integrations/…/{aws,log-sources,vcs,delivery}     ``manage_integrations`` permission key
                                                        (owner/admin roles; owner structural)
GET  /response/…/actions/ (+ propose/approve/…)         active membership (any role)
POST /membership/invitations/persona/                   workspace owner or admin (RBAC role)
POST /membership/invitations/persona/<id>/<action>/     workspace owner or admin (RBAC role)
======================================================  =============================================

NOTE (named security-posture observation, deliberately pinned as-is, not
"fixed" here): the seeded VIEWER role bundle carries only ``view_*`` keys, yet
finding-status changes, finding/vocabulary tag writes, and response-action
propose/approve are membership-gated, not capability-gated — so a viewer CAN
mutate them. The controllers document this as intentional ("any workspace
member may act"). If that stance changes, flip the gates to
``has_workspace_permission("manage_findings"/"manage_cases")`` and update the
matrix rows below — the deny assertions are already written to make that a
one-line change.
"""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.utils import timezone

from infrastructure.persistence.findings.models import Finding
from infrastructure.persistence.users.models import CustomUser

INVITE_URL = "/membership/invitations/persona/"
ACCEPT_URL = "/membership/invitations/persona/accept/"

_PASSWORD = "RbacMatrix2026!"
_WEBHOOK = "https://hooks.slack.com/services/T000/B000/abcdefghijklmnop"

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _join(api_client, owner, ws, *, persona, email, team=None, role=None):
    """Owner invites via the real endpoint; recipient accepts via the magic link."""
    api_client.force_authenticate(owner)
    body = {"workspace_id": str(ws.id), "email": email, "persona": persona}
    if team is not None:
        body["team_id"] = str(team.id)
    if role is not None:
        body["role"] = role
    created = api_client.post(INVITE_URL, body, format="json")
    assert created.status_code == 201, created.data
    api_client.force_authenticate()
    accepted = api_client.post(ACCEPT_URL, {"token": created.data["token"], "password": _PASSWORD}, format="json")
    assert accepted.status_code == 200, accepted.data
    return CustomUser.objects.get(email=email)


@pytest.fixture
def org(api_client, workspace_factory, team_factory, user_factory):
    """The backbone org: owner + admin + analyst(member) + viewer, all joined
    through the real invitation endpoints, plus an authenticated outsider."""
    call_command("seed_workspace_roles")
    ws = workspace_factory()
    owner = ws.workspace_owner
    team = team_factory(workspace=ws, created_by=owner, members=[owner])

    admin = _join(api_client, owner, ws, persona="admin", email="root@rbac.example")
    analyst = _join(api_client, owner, ws, persona="contributor", email="analyst@rbac.example", team=team)
    viewer = _join(api_client, owner, ws, persona="auditor", email="viewer@rbac.example")
    outsider = user_factory()

    class Org:
        pass

    org = Org()
    org.ws, org.owner, org.team = ws, owner, team
    org.admin, org.analyst, org.viewer, org.outsider = admin, analyst, viewer, outsider
    return org


def _finding(ws) -> Finding:
    now = timezone.now()
    return Finding.objects.create(
        workspace=ws,
        source="cloud_posture.prowler",
        fingerprint="rbac-fp-1",
        asset_urn="urn:aws:s3:::rbac-bucket",
        severity="high",
        status="open",
        title="Public S3 bucket",
        first_seen_at=now,
        last_seen_at=now,
    )


def _as(api_client, user):
    api_client.force_authenticate(user)
    return api_client


class TestJoinedMembershipRows:
    def test_roles_landed_as_invited(self, org):
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        rows = {
            m.user.email: m.role for m in WorkspaceMembership.objects.filter(workspace=org.ws).select_related("user")
        }
        assert rows["root@rbac.example"] == "admin"
        assert rows["analyst@rbac.example"] == "member"
        assert rows["viewer@rbac.example"] == "viewer"

    def test_real_workspace_create_scaffolds_the_owner_membership(self, api_client, user_factory):
        """The onboarding walk's create endpoint writes the OWNER membership row
        (``ensure_workspace_scaffolding``), so membership-gated surfaces (findings,
        tags, response) pass for the founder without any invite step."""
        from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

        founder = user_factory()
        api_client.force_authenticate(founder)
        created = api_client.post("/workspaces/create/", {"workspace_name": "Founder SOC"}, format="json")
        assert created.status_code == 201, created.data

        ws = Workspace.objects.get(workspace_owner=founder)
        membership = WorkspaceMembership.objects.get(workspace=ws, user=founder)
        assert membership.role == WorkspaceMembership.Role.OWNER
        assert membership.status == WorkspaceMembership.Status.ACTIVE
        assert api_client.get(f"/findings/workspaces/{ws.id}/").status_code == 200


class TestFindingsCapabilities:
    def test_findings_read_allow_and_deny(self, api_client, org):
        url = f"/findings/workspaces/{org.ws.id}/"
        assert _as(api_client, org.admin).get(url).status_code == 200
        assert _as(api_client, org.analyst).get(url).status_code == 200
        assert _as(api_client, org.viewer).get(url).status_code == 200
        assert _as(api_client, org.outsider).get(url).status_code == 403
        api_client.force_authenticate()
        assert api_client.get(url).status_code in (401, 403)

    def test_finding_status_change_is_membership_gated(self, api_client, org):
        finding = _finding(org.ws)
        url = f"/findings/workspaces/{org.ws.id}/{finding.id}/status/"

        # DENY: an authenticated non-member can never touch the lifecycle.
        assert _as(api_client, org.outsider).post(url, {"action": "resolve"}, format="json").status_code == 403

        # ALLOW: analyst resolves; viewer reopens (the documented "any member" contract).
        resp = _as(api_client, org.analyst).post(url, {"action": "resolve"}, format="json")
        assert resp.status_code == 200, resp.data
        resp = _as(api_client, org.viewer).post(url, {"action": "reopen"}, format="json")
        assert resp.status_code == 200, resp.data
        finding.refresh_from_db()
        assert finding.status == "open"

    def test_finding_tagging_is_membership_gated(self, api_client, org):
        finding = _finding(org.ws)
        url = f"/findings/workspaces/{org.ws.id}/{finding.id}/tags/"
        assert _as(api_client, org.outsider).post(url, {"add": ["urgent"]}, format="json").status_code == 403
        resp = _as(api_client, org.analyst).post(url, {"add": ["urgent"]}, format="json")
        assert resp.status_code == 200, resp.data
        assert [t["slug"] for t in resp.data["data"]["tags"]] == ["urgent"]

    def test_sample_data_mode_is_owner_only(self, api_client, org):
        url = f"/findings/workspaces/{org.ws.id}/sample-data/mode/"
        body = {"enabled": False}
        assert _as(api_client, org.admin).post(url, body, format="json").status_code == 403
        assert _as(api_client, org.analyst).post(url, body, format="json").status_code == 403
        assert _as(api_client, org.outsider).post(url, body, format="json").status_code == 403
        assert _as(api_client, org.owner).post(url, body, format="json").status_code == 200


class TestTagVocabularyCapabilities:
    def _create_tag(self, api_client, org, slug="triage-queue"):
        resp = _as(api_client, org.analyst).post(
            f"/tagging/workspaces/{org.ws.id}/tags/", {"name": slug}, format="json"
        )
        assert resp.status_code == 201, resp.data
        return resp.data["data"]["id"]

    def test_tag_create_member_gated(self, api_client, org):
        url = f"/tagging/workspaces/{org.ws.id}/tags/"
        assert _as(api_client, org.outsider).post(url, {"name": "nope"}, format="json").status_code == 403
        assert _as(api_client, org.viewer).post(url, {"name": "viewer-tag"}, format="json").status_code == 201

    def test_tag_rename_and_delete_admin_gated(self, api_client, org):
        tag_id = self._create_tag(api_client, org)
        detail = f"/tagging/workspaces/{org.ws.id}/tags/{tag_id}/"

        # DENY: analyst and viewer cannot mutate the shared vocabulary.
        assert _as(api_client, org.analyst).patch(detail, {"name": "hijack"}, format="json").status_code == 403
        assert _as(api_client, org.viewer).patch(detail, {"name": "hijack"}, format="json").status_code == 403
        assert _as(api_client, org.analyst).delete(detail).status_code == 403

        # ALLOW: admin renames and deletes.
        resp = _as(api_client, org.admin).patch(detail, {"name": "renamed"}, format="json")
        assert resp.status_code == 200, resp.data
        assert _as(api_client, org.admin).delete(detail).status_code == 200


class TestIntegrationsCapabilities:
    """Every integrations surface is behind ``manage_integrations`` — owner/admin
    roles carry it; analyst (member) and viewer do NOT."""

    @pytest.mark.parametrize(
        "suffix",
        ["aws/", "log-sources/", "vcs-connections/", "delivery-connections/"],
    )
    def test_list_allow_and_deny(self, api_client, org, suffix):
        url = f"/integrations/workspaces/{org.ws.id}/{suffix}"
        assert _as(api_client, org.owner).get(url).status_code == 200
        assert _as(api_client, org.admin).get(url).status_code == 200
        assert _as(api_client, org.analyst).get(url).status_code == 403
        assert _as(api_client, org.viewer).get(url).status_code == 403
        assert _as(api_client, org.outsider).get(url).status_code == 403

    def test_delivery_connection_create_admin_allowed_member_denied(self, api_client, org):
        url = f"/integrations/workspaces/{org.ws.id}/delivery-connections/"
        payload = {"kind": "slack", "name": "Alerts", "auth_mode": "webhook_url", "secret": _WEBHOOK}
        assert _as(api_client, org.analyst).post(url, payload, format="json").status_code == 403
        assert _as(api_client, org.viewer).post(url, payload, format="json").status_code == 403
        resp = _as(api_client, org.admin).post(url, payload, format="json")
        assert resp.status_code == 201, resp.data


class TestResponseActionCapabilities:
    def test_actions_are_membership_gated(self, api_client, org):
        import uuid

        base = f"/response/workspaces/{org.ws.id}/actions/"
        # DENY: outsider is walled off list + approve.
        assert _as(api_client, org.outsider).get(base).status_code == 403
        assert (
            _as(api_client, org.outsider)
            .post(f"{base}{uuid.uuid4()}/approve/", {"justification": "x"}, format="json")
            .status_code
            == 403
        )
        # ALLOW past the gate: members (any role — the human-in-the-loop gate is
        # membership, not capability) reach the service; an unknown id is a 404,
        # never a 403.
        assert _as(api_client, org.analyst).get(base).status_code == 200
        assert _as(api_client, org.viewer).get(base).status_code == 200
        resp = _as(api_client, org.viewer).post(f"{base}{uuid.uuid4()}/approve/", {"justification": "x"}, format="json")
        assert resp.status_code != 403, resp.data


class TestInvitationCapabilities:
    def _invite_body(self, org, email):
        return {"workspace_id": str(org.ws.id), "email": email, "persona": "auditor"}

    def test_member_and_viewer_cannot_invite(self, api_client, org):
        resp = _as(api_client, org.analyst).post(INVITE_URL, self._invite_body(org, "a@x.example"), format="json")
        assert resp.status_code == 403, resp.data
        resp = _as(api_client, org.viewer).post(INVITE_URL, self._invite_body(org, "b@x.example"), format="json")
        assert resp.status_code == 403, resp.data
        resp = _as(api_client, org.outsider).post(INVITE_URL, self._invite_body(org, "c@x.example"), format="json")
        assert resp.status_code == 403, resp.data

    def test_admin_can_invite_and_manage(self, api_client, org):
        created = _as(api_client, org.admin).post(INVITE_URL, self._invite_body(org, "new@x.example"), format="json")
        assert created.status_code == 201, created.data
        invitation_id = created.data["invitation_id"]

        # DENY: analyst cannot cancel the pending invite.
        resp = _as(api_client, org.analyst).post(f"{INVITE_URL}{invitation_id}/cancel/", {}, format="json")
        assert resp.status_code == 403, resp.data

        # ALLOW: admin cancels it.
        resp = _as(api_client, org.admin).post(f"{INVITE_URL}{invitation_id}/cancel/", {}, format="json")
        assert resp.status_code == 200, resp.data
        assert resp.data["status"] == "revoked"
