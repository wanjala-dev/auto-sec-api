"""Integration tests: org-level login activity + sessions + recycle-bin
delete (T2-S4).

- GET  /identity/workspaces/<id>/login-activity/  — admin-only, ACTIVE
  members (incl. owner without a membership row), login-ish event codes
  only, minus this workspace's exclusions, full detail (ip + raw UA —
  decided behavior), filters, 20/page, query-count guard.
- GET  /identity/workspaces/<id>/sessions/        — ACTIVE members'
  active sessions, -last_seen_at, query-count guard.
- DELETE /identity/workspaces/<id>/login-activity/<event_id>/ — hides
  for THIS workspace only via exclusion row + recycle bin; restorable;
  hard-delete purges the exclusion only, never the AuthAuditEvent.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from infrastructure.persistence.recycle_bin.models import RecycleBinEntry
from infrastructure.persistence.users.models import (
    AuthAuditEvent,
    CustomUser,
    UserSession,
    WorkspaceLoginActivityExclusion,
)
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = pytest.mark.django_db

LIST_URL = "workspace-login-activity"
DELETE_URL = "workspace-login-activity-delete"
SESSIONS_URL = "workspace-sessions"
SELF_URL = "my-login-activity"


def _make_user(email) -> CustomUser:
    return CustomUser.objects.create_user(email=email, username=email.split("@")[0], password="x")


def _membership(workspace, user, *, role="member", status="active") -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role, status=status)


def _session(user, jti, *, revoked=False, expired=False, last_seen=None) -> UserSession:
    now = timezone.now()
    return UserSession.objects.create(
        user=user,
        refresh_jti=jti,
        login_method="password",
        device_type="desktop",
        browser="Chrome",
        os="Mac OS X",
        geo_city="Nairobi",
        geo_country="Kenya",
        ip_address="203.0.113.7",
        last_seen_at=last_seen or now,
        expires_at=(now - timedelta(days=1)) if expired else (now + timedelta(days=30)),
        revoked_at=now if revoked else None,
    )


def _event(user, *, event_code="auth.login", success=True, session=None, ip="203.0.113.9"):
    return AuthAuditEvent.objects.create(
        user=user,
        session=session,
        email=user.email,
        event_code=event_code,
        success=success,
        ip_address=ip,
        user_agent="pytest-browser/1.0",
    )


@pytest.fixture
def org(workspace_factory, user_factory):
    """Workspace A with an admin (role=admin, ACTIVE) and a member."""
    workspace = workspace_factory()
    admin = user_factory(email="orgadmin@example.com")
    member = user_factory(email="orgmember@example.com")
    _membership(workspace, admin, role="admin")
    _membership(workspace, member, role="member")
    return workspace, admin, member


def _list(api_client, workspace, params=None):
    return api_client.get(reverse(LIST_URL, kwargs={"workspace_id": workspace.id}), params or {})


class TestWorkspaceLoginActivityAccess:
    def test_requires_authentication(self, api_client, org):
        workspace, _admin, _member = org
        assert _list(api_client, workspace).status_code == 401

    @pytest.mark.parametrize("role", ["member", "viewer"])
    def test_non_admin_roles_are_403(self, api_client, org, user_factory, role):
        workspace, _admin, _member = org
        user = user_factory()
        _membership(workspace, user, role=role)
        api_client.force_authenticate(user=user)
        assert _list(api_client, workspace).status_code == 403
        assert api_client.get(reverse(SESSIONS_URL, kwargs={"workspace_id": workspace.id})).status_code == 403

    def test_owner_without_membership_row_can_access(self, api_client, workspace_factory):
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        # Guarantee there is NO membership row — IsWorkspaceAdmin admits
        # the owner via workspace_owner_id, and the read model must
        # include the owner's events the same way.
        WorkspaceMembership.objects.filter(workspace=workspace, user=owner).delete()
        _event(owner)
        api_client.force_authenticate(user=owner)

        response = _list(api_client, workspace)
        assert response.status_code == 200
        assert response.data["count"] == 1
        assert response.data["results"][0]["member"]["email"] == owner.email


class TestWorkspaceLoginActivityList:
    def test_admin_sees_only_own_org_members_events(self, api_client, org, workspace_factory, user_factory):
        workspace_a, admin, member = org
        workspace_b = workspace_factory()
        outsider = user_factory(email="other-org@example.com")
        _membership(workspace_b, outsider, role="member")
        _event(member)
        _event(outsider)
        api_client.force_authenticate(user=admin)

        response = _list(api_client, workspace_a)
        assert response.status_code == 200
        emails = {row["member"]["email"] for row in response.data["results"]}
        assert emails == {member.email}

    def test_multi_org_members_events_appear_in_both_orgs(self, api_client, org, workspace_factory, user_factory):
        workspace_a, admin_a, _member = org
        workspace_b = workspace_factory()
        admin_b = user_factory(email="admin-b@example.com")
        _membership(workspace_b, admin_b, role="admin")
        shared = user_factory(email="shared-member@example.com")
        _membership(workspace_a, shared)
        _membership(workspace_b, shared)
        event = _event(shared)

        api_client.force_authenticate(user=admin_a)
        rows_a = _list(api_client, workspace_a).data["results"]
        api_client.force_authenticate(user=admin_b)
        rows_b = _list(api_client, workspace_b).data["results"]

        assert event.id in {row["id"] for row in rows_a}
        assert event.id in {row["id"] for row in rows_b}

    def test_inactive_membership_events_are_excluded(self, api_client, org, user_factory):
        workspace, admin, _member = org
        suspended = user_factory(email="suspended@example.com")
        _membership(workspace, suspended, status="suspended")
        _event(suspended)
        api_client.force_authenticate(user=admin)
        assert _list(api_client, workspace).data["count"] == 0

    def test_non_login_event_codes_are_excluded(self, api_client, org):
        workspace, admin, member = org
        _event(member, event_code="auth.otp_verify")
        _event(member, event_code="auth.password_reset_requested")
        _event(member, event_code="auth.logout")
        _event(member, event_code="auth.session_revoked")
        _event(member, event_code="auth.login_failed", success=False)
        api_client.force_authenticate(user=admin)

        response = _list(api_client, workspace)
        codes = {row["event_code"] for row in response.data["results"]}
        assert codes == {"auth.logout", "auth.session_revoked", "auth.login_failed"}

    def test_full_detail_includes_member_ip_ua_and_session(self, api_client, org):
        workspace, admin, member = org
        session = _session(member, "org-detail-jti")
        _event(member, session=session)
        api_client.force_authenticate(user=admin)

        (row,) = _list(api_client, workspace).data["results"]
        # Decided behavior: org admins get FULL detail incl. ip + raw UA.
        assert row["ip_address"] == "203.0.113.9"
        assert row["user_agent"] == "pytest-browser/1.0"
        assert row["member"] == {
            "id": str(member.id),
            "email": member.email,
            "display_name": member.username,
        }
        assert row["session"] == {
            "id": str(session.id),
            "device_type": "desktop",
            "browser": "Chrome",
            "os": "Mac OS X",
            "geo_city": "Nairobi",
            "geo_country": "Kenya",
            "is_active": True,
        }

    def test_paginates_at_20(self, api_client, org):
        workspace, admin, member = org
        for _ in range(25):
            _event(member)
        api_client.force_authenticate(user=admin)
        response = _list(api_client, workspace)
        assert response.data["count"] == 25
        assert len(response.data["results"]) == 20

    def test_user_id_event_code_and_success_filters(self, api_client, org):
        workspace, admin, member = org
        _event(admin, event_code="auth.login")
        _event(member, event_code="auth.login_failed", success=False)
        api_client.force_authenticate(user=admin)

        response = _list(api_client, workspace, {"user_id": str(member.id)})
        assert response.data["count"] == 1
        assert response.data["results"][0]["member"]["id"] == str(member.id)

        response = _list(api_client, workspace, {"event_code": "auth.login"})
        assert response.data["count"] == 1

        response = _list(api_client, workspace, {"success": "false"})
        assert response.data["count"] == 1
        assert response.data["results"][0]["event_code"] == "auth.login_failed"

    def test_invalid_filters_are_400(self, api_client, org):
        workspace, admin, _member = org
        api_client.force_authenticate(user=admin)
        # event_code outside the login-ish module constant is rejected,
        # not silently empty.
        assert _list(api_client, workspace, {"event_code": "auth.otp_verify"}).status_code == 400
        assert _list(api_client, workspace, {"user_id": "not-a-uuid"}).status_code == 400
        assert _list(api_client, workspace, {"success": "banana"}).status_code == 400
        assert _list(api_client, workspace, {"from": "not-a-date"}).status_code == 400

    def test_date_filters_include_bare_date_end_of_day(self, api_client, org):
        workspace, admin, member = org
        now = timezone.now()
        old = _event(member)
        mid = _event(member)
        new = _event(member)
        AuthAuditEvent.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=10))
        AuthAuditEvent.objects.filter(pk=mid.pk).update(created_at=now - timedelta(days=5))
        AuthAuditEvent.objects.filter(pk=new.pk).update(created_at=now)
        api_client.force_authenticate(user=admin)

        response = _list(api_client, workspace, {"from": (now - timedelta(days=5)).isoformat()})
        assert response.data["count"] == 2  # mid (inclusive bound) + new

        # Bare dates expand to the whole local calendar day (shared
        # end-of-day helper with the self view).
        mid_local_date = timezone.localtime(now - timedelta(days=5)).date().isoformat()
        response = _list(api_client, workspace, {"from": mid_local_date, "to": mid_local_date})
        assert response.data["count"] == 1
        assert response.data["results"][0]["id"] == mid.id


class TestWorkspaceLoginActivityDelete:
    def _delete(self, api_client, workspace, event):
        return api_client.delete(reverse(DELETE_URL, kwargs={"workspace_id": workspace.id, "event_id": event.id}))

    def test_trash_hides_for_this_workspace_only(self, api_client, org, workspace_factory, user_factory):
        workspace_a, admin_a, _member = org
        workspace_b = workspace_factory()
        admin_b = user_factory(email="delete-admin-b@example.com")
        _membership(workspace_b, admin_b, role="admin")
        shared = user_factory(email="delete-shared@example.com")
        _membership(workspace_a, shared)
        _membership(workspace_b, shared)
        event = _event(shared)

        api_client.force_authenticate(user=admin_a)
        assert self._delete(api_client, workspace_a, event).status_code == 204

        # Hidden in A…
        assert event.id not in {row["id"] for row in _list(api_client, workspace_a).data["results"]}
        # …still visible in B…
        api_client.force_authenticate(user=admin_b)
        assert event.id in {row["id"] for row in _list(api_client, workspace_b).data["results"]}
        # …and the member's own self view is untouched.
        api_client.force_authenticate(user=shared)
        self_rows = api_client.get(reverse(SELF_URL)).data["results"]
        assert event.id in {row["id"] for row in self_rows}

        # The audit event survives; the recycle bin holds the exclusion.
        assert AuthAuditEvent.objects.filter(id=event.id).exists()
        exclusion = WorkspaceLoginActivityExclusion.objects.get(workspace=workspace_a, event=event)
        entry = RecycleBinEntry.objects.get(entity_type="login_activity", entity_id=str(exclusion.id))
        assert str(entry.workspace_id) == str(workspace_a.id)
        assert shared.email in entry.entity_name

    def test_delete_is_idempotent_204(self, api_client, org):
        workspace, admin, member = org
        event = _event(member)
        api_client.force_authenticate(user=admin)

        assert self._delete(api_client, workspace, event).status_code == 204
        assert self._delete(api_client, workspace, event).status_code == 204
        assert WorkspaceLoginActivityExclusion.objects.filter(workspace=workspace, event=event).count() == 1
        assert RecycleBinEntry.objects.filter(entity_type="login_activity").count() == 1

    def test_404_when_event_not_in_workspace(self, api_client, org, workspace_factory, user_factory):
        workspace_a, admin, _member = org
        workspace_b = workspace_factory()
        outsider = user_factory(email="delete-outsider@example.com")
        _membership(workspace_b, outsider)
        foreign_event = _event(outsider)
        api_client.force_authenticate(user=admin)

        assert self._delete(api_client, workspace_a, foreign_event).status_code == 404
        assert not WorkspaceLoginActivityExclusion.objects.filter(event=foreign_event).exists()

    def test_restore_from_recycle_bin_brings_event_back(self, api_client, org):
        workspace, admin, member = org
        event = _event(member)
        api_client.force_authenticate(user=admin)
        assert self._delete(api_client, workspace, event).status_code == 204

        exclusion = WorkspaceLoginActivityExclusion.objects.get(workspace=workspace, event=event)
        entry = RecycleBinEntry.objects.get(entity_type="login_activity", entity_id=str(exclusion.id))
        response = api_client.post(reverse("recycle-bin-restore", kwargs={"entry_id": entry.id}))
        assert response.status_code == 200

        # Exclusion row gone → the event reappears in the org view.
        assert not WorkspaceLoginActivityExclusion.objects.filter(id=exclusion.id).exists()
        assert event.id in {row["id"] for row in _list(api_client, workspace).data["results"]}

    def test_hard_delete_purges_exclusion_only_event_survives(self, api_client, org):
        workspace, admin, member = org
        event = _event(member)
        api_client.force_authenticate(user=admin)
        assert self._delete(api_client, workspace, event).status_code == 204

        exclusion = WorkspaceLoginActivityExclusion.objects.get(workspace=workspace, event=event)
        entry = RecycleBinEntry.objects.get(entity_type="login_activity", entity_id=str(exclusion.id))
        response = api_client.delete(reverse("recycle-bin-delete", kwargs={"entry_id": entry.id}))
        assert response.status_code == 204

        # The append-only audit event is NEVER touched; only the
        # exclusion marker is purged.
        assert AuthAuditEvent.objects.filter(id=event.id).exists()
        assert not WorkspaceLoginActivityExclusion.objects.filter(id=exclusion.id).exists()
        assert not RecycleBinEntry.objects.filter(id=entry.id).exists()


class TestWorkspaceSessions:
    def _get(self, api_client, workspace):
        return api_client.get(reverse(SESSIONS_URL, kwargs={"workspace_id": workspace.id}))

    def test_lists_only_active_sessions_of_active_members(self, api_client, org, workspace_factory, user_factory):
        workspace, admin, member = org
        now = timezone.now()
        active = _session(member, "ws-active-jti", last_seen=now - timedelta(minutes=5))
        _session(member, "ws-revoked-jti", revoked=True)
        _session(member, "ws-expired-jti", expired=True)
        owner_session = _session(workspace.workspace_owner, "ws-owner-jti", last_seen=now)
        outsider = user_factory(email="sessions-outsider@example.com")
        _membership(workspace_factory(), outsider)
        _session(outsider, "ws-outsider-jti")
        api_client.force_authenticate(user=admin)

        response = self._get(api_client, workspace)
        assert response.status_code == 200
        ids = [row["id"] for row in response.data]
        # Owner included (even via ownership alone), ordered -last_seen_at.
        assert ids == [str(owner_session.id), str(active.id)]

        row = response.data[1]
        assert row["member"]["email"] == member.email
        assert row["ip_address"] == "203.0.113.7"  # full detail per decision
        assert row["is_active"] is True

    def test_member_role_is_403(self, api_client, org):
        workspace, _admin, member = org
        api_client.force_authenticate(user=member)
        assert self._get(api_client, workspace).status_code == 403


class TestWorkspaceLoginActivityQueryCounts:
    def _count(self, api_client, url) -> int:
        with CaptureQueriesContext(connection) as ctx:
            response = api_client.get(url)
            assert response.status_code == 200
        return len(ctx.captured_queries)

    def test_activity_list_query_count_constant_wrt_rows(self, api_client, org, user_factory):
        workspace, admin, member = org
        url = reverse(LIST_URL, kwargs={"workspace_id": workspace.id})
        for i in range(3):
            _event(member, session=_session(member, f"org-guard-jti-{i}"))
        api_client.force_authenticate(user=admin)

        self._count(api_client, url)  # warm one-time caches
        baseline = self._count(api_client, url)

        extra_member = user_factory(email="org-guard-extra@example.com")
        _membership(workspace, extra_member)
        for i in range(3, 15):
            owner = member if i % 2 else extra_member
            _event(owner, session=_session(owner, f"org-guard-jti-{i}"))
        grown = self._count(api_client, url)

        assert grown == baseline, (
            f"Org login-activity N+1 regression: {baseline} queries with 3 rows "
            f"but {grown} with 15 — member + session must ride the select_related join."
        )

    def test_sessions_list_query_count_constant_wrt_rows(self, api_client, org, user_factory):
        workspace, admin, member = org
        url = reverse(SESSIONS_URL, kwargs={"workspace_id": workspace.id})
        for i in range(3):
            _session(member, f"org-sess-guard-{i}")
        api_client.force_authenticate(user=admin)

        self._count(api_client, url)  # warm one-time caches
        baseline = self._count(api_client, url)

        extra_member = user_factory(email="org-sess-extra@example.com")
        _membership(workspace, extra_member)
        for i in range(3, 15):
            _session(extra_member if i % 2 else member, f"org-sess-guard-{i}")
        grown = self._count(api_client, url)

        assert grown == baseline, (
            f"Org sessions N+1 regression: {baseline} queries with 3 rows but "
            f"{grown} with 15 — the member block must ride the select_related join."
        )
