"""Django adapter for ``CommitHookPort``.

Wraps ``django.db.transaction.on_commit``.  Django's helper already
handles the "no transaction in progress" case by running the callback
immediately, so this adapter is a one-liner — but the port indirection
is what keeps application code framework-free.
"""
from __future__ import annotations

from typing import Callable

from django.db import transaction

from components.knowledge.application.ports.commit_hook_port import (
    CommitHookPort,
)


class DjangoCommitHookAdapter(CommitHookPort):
    """Implements ``CommitHookPort`` via Django's transaction hook."""

    def on_commit(self, callback: Callable[[], None]) -> None:
        transaction.on_commit(callback)
