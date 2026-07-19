"""Port for "run this after the current DB transaction commits".

Tier 2 #7 needs to dispatch the Celery reindex task only after the
caller's save transaction is durable.  Doing the dispatch earlier
risks the worker reading pre-commit state — a real race the
celery-tasks rule §3 calls out.

In production the adapter wraps ``django.db.transaction.on_commit``.
Outside a transaction (e.g. unit tests, management commands), the
adapter falls through to immediate invocation so callers don't have
to special-case that path.

Keeps the Explicit Architecture rule honest: application code does
not import ``django.db``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable


class CommitHookPort(ABC):
    """Abstract contract for the on-commit dispatcher."""

    @abstractmethod
    def on_commit(self, callback: Callable[[], None]) -> None:
        """Schedule ``callback`` to run after the current transaction
        commits.  If there is no surrounding transaction, run it
        immediately."""
        ...
