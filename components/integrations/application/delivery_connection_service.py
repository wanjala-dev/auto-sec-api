"""Application service for delivery-connection lifecycle (ADR 0016 D2).

Framework-free: the repository, the adapter resolver, and the crypto primitives are
injected by the composition root. Mirrors ``VcsConnectionService`` so the two connector
lifecycles read the same way.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DeliveryConnectionService:
    _repo: Any
    _resolve_adapter: Any  # (kind) -> DeliveryChannelPort
    _encrypt: Any  # (plaintext) -> ciphertext
    _decrypt: Any  # (ciphertext) -> plaintext

    def list_connections(self, workspace_id):
        return self._repo.list_for_workspace(workspace_id)

    def get_connection(self, workspace_id, connection_id):
        return self._repo.get(workspace_id, connection_id)

    def create_connection(
        self,
        *,
        workspace_id,
        kind: str,
        name: str,
        auth_mode: str,
        secret: str,
        channel: str = "",
        min_severity: str,
        events,
        created_by_id=None,
    ):
        connection = self._repo.create(
            workspace_id=workspace_id,
            kind=kind,
            name=name,
            auth_mode=auth_mode,
            secret_ciphertext=self._encrypt(secret),
            config={"channel": channel} if channel else {},
            min_severity=min_severity,
            events=list(events),
            created_by_id=created_by_id,
        )
        logger.info(
            "delivery_connection_created connection_id=%s workspace_id=%s kind=%s auth_mode=%s",
            connection.id,
            workspace_id,
            kind,
            auth_mode,
        )
        return connection

    def update_connection(
        self,
        connection,
        *,
        name=None,
        auth_mode=None,
        secret=None,
        channel=None,
        min_severity=None,
        events=None,
        status=None,
        is_enabled=None,
    ):
        # A supplied secret is re-encrypted (rotation); an omitted one leaves the
        # stored credential untouched, so editing a channel label cannot wipe auth.
        secret_ciphertext = self._encrypt(secret) if secret else None
        config = None
        if channel is not None:
            config = {**(connection.config or {}), "channel": channel}
        connection = self._repo.update(
            connection,
            name=name,
            auth_mode=auth_mode,
            secret_ciphertext=secret_ciphertext,
            config=config,
            min_severity=min_severity,
            events=None if events is None else list(events),
            status=status,
            is_enabled=is_enabled,
        )
        logger.info(
            "delivery_connection_updated connection_id=%s workspace_id=%s secret_rotated=%s",
            connection.id,
            connection.workspace_id,
            bool(secret),
        )
        return connection

    def delete_connection(self, connection) -> None:
        logger.info(
            "delivery_connection_deleted connection_id=%s workspace_id=%s",
            connection.id,
            connection.workspace_id,
        )
        self._repo.delete(connection)

    def verify_connection(self, connection):
        """Probe the destination and stamp the outcome onto the row.

        Always returns the connection — a failed probe is expressed as
        ``status="error"`` + ``last_error``, never as an exception or a 5xx. The
        operator needs to see *why* it failed in the panel.
        """
        secret = self._decrypt(connection.secret_ciphertext)
        if not secret:
            return self._repo.mark_error(connection.id, "The connection has no stored credential.")

        try:
            adapter = self._resolve_adapter(connection.kind)
        except Exception as exc:  # UnsupportedDeliveryChannelError — no adapter registered
            return self._repo.mark_error(connection.id, f"{connection.kind} is not available: {exc}")

        health = adapter.verify(self._to_resolved(connection, secret))
        logger.info(
            "delivery_connection_verified connection_id=%s workspace_id=%s ok=%s",
            connection.id,
            connection.workspace_id,
            health.ok,
        )
        if not health.ok:
            return self._repo.mark_error(connection.id, health.detail or "Verification failed.")
        return self._repo.mark_verified(connection.id, ok=True)

    @staticmethod
    def _to_resolved(connection, secret: str):
        from components.integrations.application.ports.delivery_channel_port import (
            ResolvedDeliveryConnection,
        )

        config = connection.config or {}
        return ResolvedDeliveryConnection(
            id=connection.id,
            kind=connection.kind,
            auth_mode=connection.auth_mode,
            secret=secret,
            name=connection.name or "",
            channel=str(config.get("channel") or ""),
            min_severity=connection.min_severity,
            events=tuple(connection.events or ()),
        )
