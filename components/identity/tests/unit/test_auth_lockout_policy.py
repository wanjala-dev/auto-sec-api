"""Unit tests for the auth lockout domain policy."""

from components.identity.domain.policies.auth_lockout_policy import (
    LockoutStatus,
    evaluate_lockout,
    lockout_window_minutes,
    should_lock,
)
from components.identity.domain.enums import LOCKOUT_THRESHOLD, LOCKOUT_WARN_AT


class TestShouldLock:
    def test_below_threshold_does_not_lock(self):
        assert should_lock(0) is False
        assert should_lock(LOCKOUT_THRESHOLD - 1) is False

    def test_at_threshold_locks(self):
        assert should_lock(LOCKOUT_THRESHOLD) is True

    def test_above_threshold_locks(self):
        assert should_lock(LOCKOUT_THRESHOLD + 5) is True


class TestEvaluateLockout:
    def test_no_failures_returns_clean_status(self):
        status = evaluate_lockout(failure_count=0, is_currently_locked=False, remaining_seconds=0)
        assert status.locked is False
        assert status.warn is False
        assert status.remaining_attempts == LOCKOUT_THRESHOLD

    def test_below_warn_threshold_no_warning(self):
        status = evaluate_lockout(failure_count=LOCKOUT_WARN_AT - 1, is_currently_locked=False, remaining_seconds=0)
        assert status.warn is False
        assert status.remaining_attempts == LOCKOUT_THRESHOLD - (LOCKOUT_WARN_AT - 1)

    def test_at_warn_threshold_warns(self):
        status = evaluate_lockout(failure_count=LOCKOUT_WARN_AT, is_currently_locked=False, remaining_seconds=0)
        assert status.warn is True

    def test_above_warn_threshold_warns(self):
        status = evaluate_lockout(failure_count=LOCKOUT_WARN_AT + 1, is_currently_locked=False, remaining_seconds=0)
        assert status.warn is True

    def test_locked_user_does_not_warn(self):
        """When already locked, warn should be False — the ship has sailed."""
        status = evaluate_lockout(failure_count=LOCKOUT_THRESHOLD, is_currently_locked=True, remaining_seconds=300)
        assert status.locked is True
        assert status.warn is False

    def test_locked_returns_remaining_seconds(self):
        status = evaluate_lockout(failure_count=LOCKOUT_THRESHOLD, is_currently_locked=True, remaining_seconds=600)
        assert status.remaining_seconds == 600

    def test_negative_remaining_seconds_clamped_to_zero(self):
        status = evaluate_lockout(failure_count=0, is_currently_locked=False, remaining_seconds=-10)
        assert status.remaining_seconds == 0

    def test_at_threshold_remaining_attempts_is_zero(self):
        status = evaluate_lockout(failure_count=LOCKOUT_THRESHOLD, is_currently_locked=True, remaining_seconds=0)
        assert status.remaining_attempts == 0

    def test_above_threshold_remaining_attempts_stays_zero(self):
        status = evaluate_lockout(failure_count=LOCKOUT_THRESHOLD + 10, is_currently_locked=True, remaining_seconds=0)
        assert status.remaining_attempts == 0


class TestLockoutStatus:
    def test_is_frozen_dataclass(self):
        status = LockoutStatus(locked=False, remaining_seconds=0, remaining_attempts=5, warn=False)
        try:
            status.locked = True
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass


class TestLockoutWindowMinutes:
    def test_returns_positive_int(self):
        minutes = lockout_window_minutes()
        assert isinstance(minutes, int)
        assert minutes > 0
