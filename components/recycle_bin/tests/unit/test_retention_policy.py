"""Unit tests for the retention policy domain object."""

from datetime import datetime, timedelta, timezone

from components.recycle_bin.domain.policies.retention_policy import RetentionPolicy


class TestRetentionPolicy:
    def test_default_retention_days(self):
        policy = RetentionPolicy()
        assert policy.trash_retention_days == 30
        assert policy.tombstone_retention_days == 30

    def test_trashed_until(self):
        policy = RetentionPolicy(trash_retention_days=14)
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert policy.trashed_until(now) == datetime(2026, 4, 15, tzinfo=timezone.utc)

    def test_tombstoned_until(self):
        policy = RetentionPolicy(tombstone_retention_days=7)
        now = datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert policy.tombstoned_until(now) == datetime(2026, 4, 8, tzinfo=timezone.utc)

    def test_custom_retention(self):
        policy = RetentionPolicy(trash_retention_days=60, tombstone_retention_days=90)
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert policy.trashed_until(now) == now + timedelta(days=60)
        assert policy.tombstoned_until(now) == now + timedelta(days=90)
