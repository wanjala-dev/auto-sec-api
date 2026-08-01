"""Application service for the VcsConnection lifecycle (ADR 0010 Phase 3).

Thin use cases — list / create / update / delete / verify — over the repository,
the VcsProvider adapter registry, and the secret envelope. ``verify`` decrypts the
token, resolves the provider's adapter, and probes reachability via
``VcsPort.verify``, recording the outcome on the row. No ORM/SDK here beyond the
injected collaborators. Mirrors LogSourceService.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VcsConnectionService:
    _repo: Any
    _resolve_adapter: Any  # (provider, token) -> VcsPort
    _encrypt: Any  # (plaintext) -> ciphertext
    _decrypt: Any  # (ciphertext) -> plaintext

    # ── Reads ────────────────────────────────────────────────────────────

    def list_connections(self, workspace_id):
        return self._repo.list_for_workspace(workspace_id)

    def get_connection(self, workspace_id, connection_id):
        return self._repo.get(workspace_id, connection_id)

    # ── Writes ───────────────────────────────────────────────────────────

    def create_connection(
        self, *, workspace_id, provider: str, name: str, repo_allowlist: list, base_url: str, token: str
    ):
        connection = self._repo.create(
            workspace_id=workspace_id,
            provider=provider,
            name=name or f"{provider} connection",
            repo_allowlist=repo_allowlist,
            base_url=base_url,
            token_ciphertext=self._encrypt(token),
        )
        logger.info(
            "vcs_connection_created connection_id=%s workspace_id=%s provider=%s",
            connection.id,
            workspace_id,
            provider,
        )
        return connection

    def update_connection(self, connection, *, name=None, repo_allowlist=None, base_url=None, status=None, token=None):
        # A supplied token is re-encrypted; an omitted token leaves the stored one untouched.
        token_ciphertext = self._encrypt(token) if token else None
        return self._repo.update(
            connection,
            name=name,
            repo_allowlist=repo_allowlist,
            base_url=base_url,
            status=status,
            token_ciphertext=token_ciphertext,
        )

    def delete_connection(self, connection) -> None:
        logger.info("vcs_connection_deleted connection_id=%s workspace_id=%s", connection.id, connection.workspace_id)
        self._repo.delete(connection)

    # ── Verify ───────────────────────────────────────────────────────────

    def verify_connection(self, connection):
        """Probe the connection's reachability and record the outcome. Success keeps
        it CONNECTED (+ last_verified_at); failure marks ERROR with a scrubbed reason.
        Never raises for an expected auth/config/probe failure."""
        token = self._decrypt(connection.token_ciphertext)
        if not token:
            return self._repo.mark_error(connection, "The connection has no stored token.")

        try:
            adapter = self._resolve_adapter(connection.provider, token)
        except Exception as exc:  # UnsupportedVcsProviderError — adapter not registered (e.g. flag off)
            return self._repo.mark_error(connection, f"{connection.provider} is not available: {exc}")

        allowlist = [r for r in (connection.repo_allowlist or []) if isinstance(r, str) and r.strip()]
        health = adapter.verify(allowlist[0] if allowlist else None)
        if health.ok:
            return self._repo.mark_verified(connection)
        return self._repo.mark_error(connection, health.detail or "Verification failed.")
