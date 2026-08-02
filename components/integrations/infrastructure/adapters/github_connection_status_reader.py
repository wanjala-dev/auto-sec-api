"""Adapter: read the non-secret ``GitHubConnection`` credential surface.

Implements :class:`GitHubConnectionStatusReadPort`. The ``integrations`` context
reads its OWN persistence model (``infrastructure.persistence.integrations.models``)
behind its own application port — the sanctioned inbound-read seam consumed by the
AI-governance credential inventory (mirrors ``BoardFindingFactsReader``).

**Secret containment (the whole point of this adapter).** ``GitHubConnection``
stores an encrypted PAT in ``token_ciphertext``. This adapter reduces that field to
a presence boolean (``has_token``) HERE — the ciphertext is loaded off the row,
compared for emptiness, and dropped; it never enters the returned DTO and is never
logged. The ``.only(...)`` clause and the ``has_token`` reduction below are the only
place the token column is ever read, and nothing downstream can reach it.
"""

from __future__ import annotations

from components.integrations.application.ports.github_connection_status_port import (
    GitHubConnectionStatus,
    GitHubConnectionStatusReadPort,
)


class GitHubConnectionStatusReader(GitHubConnectionStatusReadPort):
    def list_statuses(self, *, workspace_id: str) -> list[GitHubConnectionStatus]:
        from infrastructure.persistence.integrations.models import GitHubConnection

        statuses: list[GitHubConnectionStatus] = []
        connections = (
            GitHubConnection.objects.filter(workspace_id=str(workspace_id))
            .only(
                "id",
                "name",
                "status",
                "repo_allowlist",
                "token_ciphertext",
                "created_at",
                "updated_at",
                "last_used_at",
            )
            .order_by("-created_at")
        )
        for conn in connections.iterator(chunk_size=100):
            allowlist = conn.repo_allowlist if isinstance(conn.repo_allowlist, list) else []
            statuses.append(
                GitHubConnectionStatus(
                    id=str(conn.id),
                    name=conn.name,
                    status=conn.status,
                    repo_allowlist=[str(repo) for repo in allowlist],
                    # Reduced to a presence boolean HERE — the ciphertext never
                    # travels past this line into the DTO (and is never logged).
                    has_token=bool(conn.token_ciphertext),
                    created_at=conn.created_at,
                    updated_at=conn.updated_at,
                    last_used_at=conn.last_used_at,
                )
            )
        return statuses
