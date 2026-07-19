"""Tests for cancellation token propagation."""

from __future__ import annotations

import pytest

from components.agents.domain.cancellation import CancellationToken, CancelledError


class TestCancellationToken:
    def test_not_cancelled_by_default(self):
        token = CancellationToken()
        assert not token.is_cancelled
        assert token.reason == ""

    def test_cancel(self):
        token = CancellationToken()
        token.cancel(reason="user requested")
        assert token.is_cancelled
        assert token.reason == "user requested"

    def test_check_raises_when_cancelled(self):
        token = CancellationToken()
        token.cancel(reason="test")
        with pytest.raises(CancelledError, match="test"):
            token.check()

    def test_check_passes_when_not_cancelled(self):
        token = CancellationToken()
        token.check()  # Should not raise

    def test_child_inherits_cancellation(self):
        parent = CancellationToken()
        child = parent.child()

        assert not child.is_cancelled
        parent.cancel(reason="parent cancelled")
        assert child.is_cancelled
        assert child.reason == "parent cancelled"

    def test_child_created_after_cancel(self):
        parent = CancellationToken()
        parent.cancel(reason="already done")

        child = parent.child()
        assert child.is_cancelled
        assert child.reason == "already done"

    def test_grandchild_propagation(self):
        grandparent = CancellationToken()
        parent = grandparent.child()
        child = parent.child()

        assert not child.is_cancelled
        grandparent.cancel(reason="top-level abort")
        assert parent.is_cancelled
        assert child.is_cancelled

    def test_cancelling_child_does_not_affect_parent(self):
        parent = CancellationToken()
        child = parent.child()

        child.cancel(reason="child only")
        assert child.is_cancelled
        assert not parent.is_cancelled

    def test_double_cancel_is_idempotent(self):
        token = CancellationToken()
        token.cancel(reason="first")
        token.cancel(reason="second")
        assert token.reason == "first"  # First reason preserved

    def test_wait_returns_true_when_cancelled(self):
        token = CancellationToken()
        token.cancel()
        assert token.wait(timeout=0.01) is True

    def test_wait_returns_false_on_timeout(self):
        token = CancellationToken()
        assert token.wait(timeout=0.01) is False

    def test_multiple_children(self):
        parent = CancellationToken()
        children = [parent.child() for _ in range(5)]

        parent.cancel(reason="all stop")
        for child in children:
            assert child.is_cancelled
