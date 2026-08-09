"""Application service for the VercelConnection lifecycle (ADR 0021 D2).

Thin use cases — list / create / update / delete / verify — over the repository,
the ``VercelApiPort`` adapter, and the secret envelope. ``verify`` decrypts the
token, probes ``GET /v2/user`` (the exact call Prowler validates credentials
with), resolves the ONE consented team, records the canonical team trio + the
token's expiry, and stamps the outcome on the row. Both failure modes surface
LOUDLY on the connection (the ADR 0008 silent-blank lesson): a revoked token
(401) and an inaccessible team never produce a quietly empty next scan. No
ORM/SDK here beyond the injected collaborators. Mirrors VcsConnectionService.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VercelConnectionService:
    _repo: Any
    _resolve_adapter: Any  # (token) -> VercelApiPort
    _encrypt: Any  # (plaintext) -> ciphertext
    _decrypt: Any  # (ciphertext) -> plaintext

    # ── Reads ────────────────────────────────────────────────────────────

    def list_connections(self, workspace_id):
        return self._repo.list_for_workspace(workspace_id)

    def get_connection(self, workspace_id, connection_id):
        return self._repo.get(workspace_id, connection_id)

    # ── Writes ───────────────────────────────────────────────────────────

    def create_connection(self, *, workspace_id, name: str, team_id: str, team_slug: str, token: str, created_by=None):
        connection = self._repo.create(
            workspace_id=workspace_id,
            name=name or "Vercel",
            team_id=team_id,
            team_slug=team_slug,
            token_ciphertext=self._encrypt(token),
            created_by=created_by,
        )
        logger.info(
            "vercel_connection_created connection_id=%s workspace_id=%s team=%s",
            connection.id,
            workspace_id,
            connection.team_ref,
        )
        return connection

    def update_connection(self, connection, *, name=None, team_id=None, team_slug=None, status=None, token=None):
        # A supplied token is re-encrypted; an omitted token leaves the stored one untouched.
        token_ciphertext = self._encrypt(token) if token else None
        return self._repo.update(
            connection,
            name=name,
            team_id=team_id,
            team_slug=team_slug,
            status=status,
            token_ciphertext=token_ciphertext,
        )

    def delete_connection(self, connection) -> None:
        logger.info(
            "vercel_connection_deleted connection_id=%s workspace_id=%s", connection.id, connection.workspace_id
        )
        self._repo.delete(connection)

    # ── Verify ───────────────────────────────────────────────────────────

    def verify_connection(self, connection):
        """Probe token validity + team access and record the outcome.

        Success records the canonical team trio (id/slug/name) + the token's expiry
        (when the API exposes it) and marks CONNECTED; any failure marks ERROR with a
        scrubbed reason. Never raises for an expected auth/config/probe failure.
        """
        token = self._decrypt(connection.token_ciphertext)
        if not token:
            return self._repo.mark_error(connection, "The connection has no stored token.")

        team_ref = connection.team_ref
        if not team_ref:
            # A connection without a team can never be scanned (the VERCEL_TEAM
            # consent pin, ADR 0021 D3) — say so instead of failing later.
            return self._repo.mark_error(connection, "No team configured — a Vercel connection must name one team.")

        adapter = self._resolve_adapter(token)

        # 1) Token probe (GET /v2/user) — an invalid/revoked token fails everything,
        #    so report it as the single root cause.
        token_health = adapter.verify_token()
        if not token_health.ok:
            return self._repo.mark_error(connection, token_health.detail or "token invalid")

        # 2) Team probe — resolve the id/slug the operator supplied to the canonical
        #    trio and confirm the token can actually read that team.
        team_health, team = adapter.get_team(team_ref)
        if not team_health.ok or team is None:
            return self._repo.mark_error(connection, team_health.detail or f"the token cannot access team {team_ref}")

        self._repo.record_team(
            connection,
            team_id=team.id,
            team_slug=team.slug,
            team_name=team.name,
            token_expires_at=adapter.get_token_expiry(),
        )
        logger.info(
            "vercel_connection_verified connection_id=%s workspace_id=%s team_id=%s",
            connection.id,
            connection.workspace_id,
            team.id,
        )
        return self._repo.mark_verified(connection)
