"""Regression: ORM→record mapping must normalize datetimes to aware UTC.

Runtime settings run USE_TZ=False (naive ORM datetimes) while test settings
run USE_TZ=True (aware). The domain compares against ``datetime.now(UTC)``,
so a naive ``expires_at`` reaching ``UserSessionRecord.is_active`` raised
TypeError on the live server (/identity/me/sessions/ 500) while every test
stayed green. ``_to_record`` now attaches UTC to naive values at the
infrastructure boundary; these tests pin that for both settings shapes.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from components.identity.infrastructure.repositories.orm_user_session_repository import (
    _aware_utc,
    _to_record,
)

pytestmark = pytest.mark.unit


def _orm_stub(**overrides):
    base = {
        "id": uuid4(),
        "user_id": uuid4(),
        "refresh_jti": "jti-1",
        "login_method": "password",
        "ip_address": "10.0.0.1",
        "user_agent": "UA",
        "device_type": "desktop",
        "browser": "Chrome",
        "browser_version": "150.0",
        "os": "Mac OS X",
        "os_version": "14.5",
        "geo_city": "",
        "geo_country": "",
        "geo_country_code": "",
        # Naive datetimes — the exact shape the ORM returns under USE_TZ=False.
        "enriched_at": None,
        "created_at": datetime(2026, 7, 16, 12, 0, 0),
        "last_seen_at": datetime(2026, 7, 16, 12, 5, 0),
        "expires_at": datetime(2026, 8, 16, 12, 0, 0),
        "revoked_at": None,
        "revoked_reason": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestAwareUtc:
    def test_naive_gets_utc_attached(self):
        naive = datetime(2026, 7, 16, 12, 0, 0)
        result = _aware_utc(naive)
        assert result.tzinfo is UTC
        assert result.replace(tzinfo=None) == naive

    def test_aware_passes_through_unchanged(self):
        aware = datetime(2026, 7, 16, 12, 0, 0, tzinfo=UTC)
        assert _aware_utc(aware) is aware

    def test_none_stays_none(self):
        assert _aware_utc(None) is None


class TestToRecordNormalization:
    def test_naive_orm_datetimes_become_aware(self):
        record = _to_record(_orm_stub())
        assert record.created_at.tzinfo is UTC
        assert record.last_seen_at.tzinfo is UTC
        assert record.expires_at.tzinfo is UTC
        assert record.enriched_at is None
        assert record.revoked_at is None

    def test_is_active_comparison_does_not_raise_with_naive_source(self):
        record = _to_record(_orm_stub())
        # This exact call raised TypeError pre-fix (naive vs aware).
        assert record.is_active(datetime.now(UTC)) is True

    def test_expired_naive_session_reports_inactive(self):
        record = _to_record(_orm_stub(expires_at=datetime(2020, 1, 1)))
        assert record.is_active(datetime.now(UTC)) is False

    def test_revoked_naive_session_reports_inactive(self):
        record = _to_record(_orm_stub(revoked_at=datetime(2026, 7, 16, 13, 0, 0)))
        assert record.revoked_at.tzinfo is UTC
        assert record.is_active(datetime.now(UTC)) is False

    def test_aware_orm_datetimes_pass_through(self):
        aware = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)
        record = _to_record(_orm_stub(expires_at=aware))
        assert record.expires_at == aware
