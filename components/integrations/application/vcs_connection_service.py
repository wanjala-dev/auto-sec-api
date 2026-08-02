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
        self,
        *,
        workspace_id,
        provider: str,
        name: str,
        repo_allowlist: list,
        base_url: str,
        token: str,
        repo_root: str = "",
        commit_identity: str = "pat_owner",
        commit_author_name: str = "",
        commit_author_email: str = "",
    ):
        connection = self._repo.create(
            workspace_id=workspace_id,
            provider=provider,
            name=name or f"{provider} connection",
            repo_allowlist=repo_allowlist,
            base_url=base_url,
            repo_root=repo_root,
            commit_identity=commit_identity,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
            token_ciphertext=self._encrypt(token),
        )
        logger.info(
            "vcs_connection_created connection_id=%s workspace_id=%s provider=%s",
            connection.id,
            workspace_id,
            provider,
        )
        return connection

    def update_connection(
        self,
        connection,
        *,
        name=None,
        repo_allowlist=None,
        base_url=None,
        repo_root=None,
        commit_identity=None,
        commit_author_name=None,
        commit_author_email=None,
        status=None,
        token=None,
    ):
        # A supplied token is re-encrypted; an omitted token leaves the stored one untouched.
        token_ciphertext = self._encrypt(token) if token else None
        return self._repo.update(
            connection,
            name=name,
            repo_allowlist=repo_allowlist,
            base_url=base_url,
            repo_root=repo_root,
            commit_identity=commit_identity,
            commit_author_name=commit_author_name,
            commit_author_email=commit_author_email,
            status=status,
            token_ciphertext=token_ciphertext,
        )

    def delete_connection(self, connection) -> None:
        logger.info("vcs_connection_deleted connection_id=%s workspace_id=%s", connection.id, connection.workspace_id)
        self._repo.delete(connection)

    # ── Verify ───────────────────────────────────────────────────────────

    def verify_connection(self, connection):
        """Probe the connection's reachability and record the outcome. First probes the
        token itself; then probes EVERY allowlisted repo (not just the first) so a repo the
        token can't reach is named, not silently masked by an accessible sibling. Success
        (token valid + all repos reachable) keeps it CONNECTED (+ last_verified_at); any
        failure marks ERROR with a scrubbed reason. Never raises for an expected
        auth/config/probe failure."""
        token = self._decrypt(connection.token_ciphertext)
        if not token:
            return self._repo.mark_error(connection, "The connection has no stored token.")

        try:
            adapter = self._resolve_adapter(connection.provider, token)
        except Exception as exc:  # UnsupportedVcsProviderError — adapter not registered (e.g. flag off)
            return self._repo.mark_error(connection, f"{connection.provider} is not available: {exc}")

        # 1) Token probe (GET /user) — an invalid/missing-scope token fails everything, so
        #    report it as the single root cause rather than N per-repo failures.
        token_health = adapter.verify(None)
        if not token_health.ok:
            return self._repo.mark_error(connection, token_health.detail or "token invalid or missing scope")

        # 2) Per-repo probe — one call per repo (allowlists are small). Aggregate the
        #    unreachable ones so the operator sees WHICH repos are blocked. A repo can
        #    fail here for a permission reason (401/403/404) OR a transient one (500 /
        #    timeout → "not reachable"); we don't claim a hard "no access" for the
        #    latter, hence "no access or unreachable".
        allowlist = [r for r in (connection.repo_allowlist or []) if isinstance(r, str) and r.strip()]
        inaccessible = [repo for repo in allowlist if not adapter.verify(repo).ok]
        if inaccessible:
            return self._repo.mark_error(
                connection, f"connected, but no access or unreachable: {', '.join(inaccessible)}"
            )

        return self._repo.mark_verified(connection)
