"""Cancellation token for propagating abort signals through agent hierarchies.

Inspired by the reference architecture's AbortController pattern where parent
abort automatically cancels all children. In Python we use threading.Event
since agent workers run in threads or Celery tasks.

Usage::

    # Parent (orchestrator or Celery task)
    parent = CancellationToken()

    # Pass to child workers
    child = parent.child()

    # In worker loop:
    if child.is_cancelled:
        raise CancelledError("Parent was cancelled")

    # Cancel from parent (propagates to all children)
    parent.cancel(reason="User requested stop")

    # Check anywhere:
    assert child.is_cancelled
    assert child.reason == "User requested stop"
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class CancelledError(Exception):
    """Raised when an operation is cancelled via a CancellationToken."""

    def __init__(self, reason: str = "Cancelled"):
        super().__init__(reason)
        self.reason = reason


class CancellationToken:
    """Thread-safe cancellation signal with parent-child propagation."""

    def __init__(self, *, parent: CancellationToken | None = None):
        self._event = threading.Event()
        self._reason: str = ""
        self._children: list[CancellationToken] = []
        self._lock = threading.Lock()
        self._parent = parent
        if parent is not None:
            parent._register_child(self)

    @property
    def is_cancelled(self) -> bool:
        """True if this token or any ancestor has been cancelled."""
        if self._event.is_set():
            return True
        if self._parent is not None:
            return self._parent.is_cancelled
        return False

    @property
    def reason(self) -> str:
        if self._reason:
            return self._reason
        if self._parent is not None:
            return self._parent.reason
        return ""

    def cancel(self, reason: str = "Cancelled") -> None:
        """Cancel this token and all children recursively."""
        with self._lock:
            if self._event.is_set():
                return
            self._reason = reason
            self._event.set()
            for child in self._children:
                child.cancel(reason=reason)

    def child(self) -> CancellationToken:
        """Create a child token that auto-cancels when this token cancels."""
        child = CancellationToken(parent=self)
        # If already cancelled, propagate immediately
        if self.is_cancelled:
            child.cancel(reason=self.reason)
        return child

    def check(self) -> None:
        """Raise CancelledError if cancelled. Call in tight loops."""
        if self.is_cancelled:
            raise CancelledError(self.reason)

    def wait(self, timeout: float | None = None) -> bool:
        """Block until cancelled or timeout. Returns True if cancelled."""
        return self._event.wait(timeout=timeout)

    def _register_child(self, child: CancellationToken) -> None:
        with self._lock:
            self._children.append(child)
