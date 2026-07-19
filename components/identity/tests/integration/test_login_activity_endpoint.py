"""Integration tests: GET /identity/me/login-activity/ (T2-S3).

Pagination (20/page), filters (event_code / success / from / to),
ownership scoping, session device summary, and an N+1 query-count guard
(constant w.r.t. row count — the repository select_relates ``session``).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from infrastructure.persistence.users.models import AuthAuditEvent, CustomUser, UserSession

pytestmark = pytest.mark.django_db

URL_NAME = "my-login-activity"


def _make_user(email) -> CustomUser:
    return CustomUser.objects.create_user(email=email, username=email.split("@")[0], password="x")


def _session(user, jti) -> UserSession:
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
        last_seen_at=now,
        expires_at=now + timedelta(days=30),
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


class TestLoginActivityList:
    def test_paginates_at_20_and_orders_newest_first(self, api_client):
        user = _make_user("activity-page@example.com")
        for _ in range(25):
            _event(user)
        api_client.force_authenticate(user=user)

        response = api_client.get(reverse(URL_NAME))
        assert response.status_code == 200
        assert response.data["count"] == 25
        assert len(response.data["results"]) == 20
        assert response.data["next"] is not None

        page2 = api_client.get(reverse(URL_NAME), {"page": 2})
        assert len(page2.data["results"]) == 5

        timestamps = [row["created_at"] for row in response.data["results"]]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_full_detail_includes_ip_ua_and_session_summary(self, api_client):
        user = _make_user("activity-detail@example.com")
        session = _session(user, "activity-jti")
        _event(user, session=session)
        api_client.force_authenticate(user=user)

        response = api_client.get(reverse(URL_NAME))
        (row,) = response.data["results"]
        assert row["ip_address"] == "203.0.113.9"
        assert row["user_agent"] == "pytest-browser/1.0"
        assert row["event_code"] == "auth.login"
        assert row["success"] is True
        assert row["session"] == {
            "id": str(session.id),
            "device_type": "desktop",
            "browser": "Chrome",
            "os": "Mac OS X",
            "geo_city": "Nairobi",
            "geo_country": "Kenya",
        }

    def test_event_without_session_serialises_null_summary(self, api_client):
        user = _make_user("activity-nosession@example.com")
        _event(user, session=None)
        api_client.force_authenticate(user=user)
        (row,) = api_client.get(reverse(URL_NAME)).data["results"]
        assert row["session"] is None

    def test_only_own_events_are_visible(self, api_client):
        me = _make_user("activity-me@example.com")
        other = _make_user("activity-other@example.com")
        _event(me)
        _event(other)
        api_client.force_authenticate(user=me)
        response = api_client.get(reverse(URL_NAME))
        assert response.data["count"] == 1

    def test_requires_authentication(self, api_client):
        assert api_client.get(reverse(URL_NAME)).status_code == 401


class TestLoginActivityFilters:
    def test_event_code_and_success_filters(self, api_client):
        user = _make_user("activity-filters@example.com")
        _event(user, event_code="auth.login", success=True)
        _event(user, event_code="auth.login_failed", success=False)
        _event(user, event_code="auth.otp_verify", success=True)
        api_client.force_authenticate(user=user)

        response = api_client.get(reverse(URL_NAME), {"event_code": "auth.login"})
        assert response.data["count"] == 1
        assert response.data["results"][0]["event_code"] == "auth.login"

        response = api_client.get(reverse(URL_NAME), {"success": "false"})
        assert response.data["count"] == 1
        assert response.data["results"][0]["event_code"] == "auth.login_failed"

        response = api_client.get(reverse(URL_NAME), {"success": "true"})
        assert response.data["count"] == 2

    def test_date_range_filters_are_inclusive(self, api_client):
        user = _make_user("activity-dates@example.com")
        now = timezone.now()
        old = _event(user)
        mid = _event(user)
        new = _event(user)
        AuthAuditEvent.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=10))
        AuthAuditEvent.objects.filter(pk=mid.pk).update(created_at=now - timedelta(days=5))
        AuthAuditEvent.objects.filter(pk=new.pk).update(created_at=now)
        api_client.force_authenticate(user=user)

        # Full ISO datetimes filter precisely (inclusive bounds).
        frm = (now - timedelta(days=5)).isoformat()
        response = api_client.get(reverse(URL_NAME), {"from": frm})
        assert response.data["count"] == 2  # mid (== bound, inclusive) + new

        response = api_client.get(
            reverse(URL_NAME),
            {"from": (now - timedelta(days=10)).isoformat(), "to": (now - timedelta(days=5)).isoformat()},
        )
        assert response.data["count"] == 2  # old + mid, both on inclusive bounds

        # Bare dates expand in the CURRENT timezone: `from` → start of day,
        # `to` → end of day, so one local calendar day covers its events.
        mid_local_date = timezone.localtime(now - timedelta(days=5)).date().isoformat()
        response = api_client.get(reverse(URL_NAME), {"from": mid_local_date, "to": mid_local_date})
        assert response.data["count"] == 1  # exactly mid's whole local day

    def test_invalid_filter_values_are_400(self, api_client):
        user = _make_user("activity-badfilters@example.com")
        api_client.force_authenticate(user=user)
        assert api_client.get(reverse(URL_NAME), {"success": "banana"}).status_code == 400
        assert api_client.get(reverse(URL_NAME), {"from": "not-a-date"}).status_code == 400
        assert api_client.get(reverse(URL_NAME), {"to": "31-12-2026"}).status_code == 400


class TestLoginActivityQueryCount:
    def _count(self, api_client) -> int:
        with CaptureQueriesContext(connection) as ctx:
            response = api_client.get(reverse(URL_NAME))
            assert response.status_code == 200
        return len(ctx.captured_queries)

    def test_query_count_is_constant_wrt_row_count(self, api_client):
        user = _make_user("activity-nplusone@example.com")
        for i in range(3):
            _event(user, session=_session(user, f"guard-jti-{i}"))
        api_client.force_authenticate(user=user)

        self._count(api_client)  # warm one-time caches (content types etc.)
        baseline = self._count(api_client)

        for i in range(3, 15):
            _event(user, session=_session(user, f"guard-jti-{i}"))
        grown = self._count(api_client)

        assert grown == baseline, (
            f"Login-activity N+1 regression: {baseline} queries with 3 rows but "
            f"{grown} with 15 — the session summary must ride the select_related join."
        )
