"""Composition root for ``CommitHookPort``."""
from __future__ import annotations

from components.knowledge.application.ports.commit_hook_port import (
    CommitHookPort,
)


def commit_hook() -> CommitHookPort:
    """Return the configured commit-hook adapter (Django in prod)."""
    from components.knowledge.infrastructure.adapters.django_commit_hook_adapter import (
        DjangoCommitHookAdapter,
    )

    return DjangoCommitHookAdapter()
