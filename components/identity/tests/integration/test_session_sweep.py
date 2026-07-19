"""Integration tests: ``identity.sweep_user_sessions`` boundaries (T2-S2).

Reconciliation (expired → revoked_reason="expired_sweep") plus the two
retention windows, exercised right at their day boundaries.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from components.identity.workers.tasks import sweep_user_sessions
from infrastructure.persistence.users.models import AuthAuditEvent, CustomUser, UserSession

pytestmark = pytest.mark.django_db


def _make_user(email="sweep-tester@example.com") -> CustomUser:
    return CustomUser.objects.create_user(email=email, username=email.split("@")[0], password="x")


def _session(user, *, jti, expires_delta, revoked_delta=None, reason="") -> UserSession:
    now = timezone.now()
    session = UserSession.objects.create(
        user=user,
        refresh_jti=jti,
        login_method="password",
        last_seen_at=now,
        expires_at=now + expires_delta,
        revoked_at=(now + revoked_delta) if revoked_delta is not None else None,
        revoked_reason=reason,
    )
    return session


class TestExpiredReconciliation:
    def test_expired_unrevoked_sessions_get_expired_sweep(self):
        user = _make_user()
        expired = _session(user, jti="expired", expires_delta=timedelta(minutes=-5))
        active = _session(user, jti="active", expires_delta=timedelta(days=30))
        already_revoked = _session(
            user, jti="revoked", expires_delta=timedelta(minutes=-5), revoked_delta=timedelta(hours=-1), reason="logout"
        )

        result = sweep_user_sessions.run()
        assert result["expired_marked"] == 1

        expired.refresh_from_db()
        assert expired.revoked_reason == "expired_sweep"
        assert expired.revoked_at is not None
        active.refresh_from_db()
        assert active.revoked_at is None
        already_revoked.refresh_from_db()
        assert already_revoked.revoked_reason == "logout"  # untouched


class TestSessionRetention:
    def test_dead_sessions_prune_at_the_retention_boundary(self, settings):
        settings.SESSION_RETENTION_DAYS = 180
        user = _make_user("sweep-retention@example.com")
        # Dead for 181 days → pruned (via either bound).
        _session(
            user,
            jti="old-revoked",
            expires_delta=timedelta(days=30),
            revoked_delta=timedelta(days=-181),
            reason="logout",
        )
        _session(user, jti="old-expired", expires_delta=timedelta(days=-181))
        # Dead for 179 days → kept.
        kept_revoked = _session(
            user,
            jti="new-revoked",
            expires_delta=timedelta(days=30),
            revoked_delta=timedelta(days=-179),
            reason="logout",
        )
        kept_active = _session(user, jti="still-active", expires_delta=timedelta(days=30))

        result = sweep_user_sessions.run()
        assert result["sessions_pruned"] == 2

        remaining = set(UserSession.objects.filter(user=user).values_list("refresh_jti", flat=True))
        assert remaining == {kept_revoked.refresh_jti, kept_active.refresh_jti}

    def test_pruned_session_leaves_audit_history_with_null_fk(self):
        user = _make_user("sweep-setnull@example.com")
        doomed = _session(
            user, jti="doomed", expires_delta=timedelta(days=30), revoked_delta=timedelta(days=-200), reason="logout"
        )
        event = AuthAuditEvent.objects.create(user=user, session=doomed, event_code="auth.login", success=True)

        sweep_user_sessions.run()

        event.refresh_from_db()
        assert event.session_id is None  # SET_NULL — history survives


class TestAuditRetention:
    def test_audit_events_prune_at_the_retention_boundary(self, settings):
        settings.AUTH_AUDIT_RETENTION_DAYS = 365
        user = _make_user("sweep-audit@example.com")
        old = AuthAuditEvent.objects.create(user=user, event_code="auth.login", success=True)
        recent = AuthAuditEvent.objects.create(user=user, event_code="auth.login", success=True)
        # created_at is auto_now_add — age the rows via queryset update.
        now = timezone.now()
        AuthAuditEvent.objects.filter(pk=old.pk).update(created_at=now - timedelta(days=366))
        AuthAuditEvent.objects.filter(pk=recent.pk).update(created_at=now - timedelta(days=364))

        result = sweep_user_sessions.run()

        assert result["audit_events_pruned"] == 1
        remaining = set(AuthAuditEvent.objects.filter(user=user).values_list("pk", flat=True))
        assert remaining == {recent.pk}

    def test_audit_prune_handles_more_than_one_batch(self, settings, monkeypatch):
        import components.identity.workers.tasks as tasks_module

        monkeypatch.setattr(tasks_module, "_PRUNE_BATCH_SIZE", 2)
        settings.AUTH_AUDIT_RETENTION_DAYS = 365
        user = _make_user("sweep-batch@example.com")
        events = [AuthAuditEvent.objects.create(user=user, event_code="auth.login", success=True) for _ in range(5)]
        AuthAuditEvent.objects.filter(pk__in=[e.pk for e in events]).update(
            created_at=timezone.now() - timedelta(days=400)
        )

        result = sweep_user_sessions.run()
        assert result["audit_events_pruned"] == 5
        assert not AuthAuditEvent.objects.filter(user=user).exists()
