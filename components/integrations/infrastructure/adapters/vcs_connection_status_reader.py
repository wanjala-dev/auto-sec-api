"""Adapter: read the non-secret ``VcsConnection`` credential surface.

Implements :class:`VcsConnectionStatusReadPort`. The ``integrations`` context
reads its OWN persistence model (``infrastructure.persistence.integrations.models``)
behind its own application port — the sanctioned inbound-read seam consumed by the
AI-governance credential inventory (mirrors ``BoardFindingFactsReader``).

**Secret containment (the whole point of this adapter).** A PAT-mode
``VcsConnection`` stores an encrypted PAT in ``token_ciphertext``. This adapter
reduces that field to a presence boolean (``has_token``) HERE — the ciphertext is
loaded off the row, checked for emptiness, and dropped; it never enters the
returned DTO and is never logged. App-mode rows store no secret at all: their
short-lived installation tokens live only in the Django cache, which this adapter
never reads — the DTO carries the (non-secret) ``installation_id`` and a
human-readable credential label instead.
"""

from __future__ import annotations

from components.integrations.application.ports.vcs_connection_status_port import (
    VcsConnectionStatus,
    VcsConnectionStatusReadPort,
)


def _credential_label(conn) -> str:
    """A human-readable, secret-free description of the credential kind."""
    if conn.auth_mode == "github_app":
        if conn.installation_id:
            return f"GitHub App installation {conn.installation_id}"
        return "GitHub App (no installation bound)"
    if conn.token_ciphertext:
        return "fine-grained PAT (encrypted)"
    return "none (no stored credential)"


class VcsConnectionStatusReader(VcsConnectionStatusReadPort):
    def list_statuses(self, *, workspace_id: str) -> list[VcsConnectionStatus]:
        from infrastructure.persistence.integrations.models import VcsConnection

        statuses: list[VcsConnectionStatus] = []
        connections = (
            VcsConnection.objects.filter(workspace_id=str(workspace_id))
            .only(
                "id",
                "provider",
                "name",
                "status",
                "auth_mode",
                "installation_id",
                "repo_allowlist",
                "token_ciphertext",
                "last_error",
                "created_at",
                "updated_at",
                "last_used_at",
            )
            .order_by("-created_at")
        )
        for conn in connections.iterator(chunk_size=100):
            allowlist = conn.repo_allowlist if isinstance(conn.repo_allowlist, list) else []
            statuses.append(
                VcsConnectionStatus(
                    id=str(conn.id),
                    provider=conn.provider,
                    name=conn.name,
                    status=conn.status,
                    auth_mode=conn.auth_mode,
                    installation_id=conn.installation_id,
                    repo_allowlist=[str(repo) for repo in allowlist],
                    # Reduced to a presence boolean HERE — the ciphertext never
                    # travels past this line into the DTO (and is never logged).
                    has_token=conn.has_usable_credential,
                    credential=_credential_label(conn),
                    last_error=conn.last_error or "",
                    created_at=conn.created_at,
                    updated_at=conn.updated_at,
                    last_used_at=conn.last_used_at,
                )
            )
        return statuses
