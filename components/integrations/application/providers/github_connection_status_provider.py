"""Composition root for the non-secret GitHub credential-status read (governance).

Wires :class:`GitHubConnectionStatusReadPort` to its ORM adapter. Provider files are
the allowed composition-root slot for own-context infrastructure imports; consumers
(the AI-governance credential inventory) resolve the port here and stay free of any
``integrations`` ORM import.

The adapter reduces the encrypted PAT to a presence boolean before it ever returns —
see :mod:`components.integrations.infrastructure.adapters.github_connection_status_reader`.
"""

from __future__ import annotations

from components.integrations.application.ports.github_connection_status_port import (
    GitHubConnectionStatusReadPort,
)


def get_github_connection_status_reader() -> GitHubConnectionStatusReadPort:
    from components.integrations.infrastructure.adapters.github_connection_status_reader import (
        GitHubConnectionStatusReader,
    )

    return GitHubConnectionStatusReader()
