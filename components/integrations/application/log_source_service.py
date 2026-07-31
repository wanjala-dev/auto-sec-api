"""Application service for the WorkspaceLogSource lifecycle (ADR 0008 Phase 3).

Thin use cases — list / create / update / delete / verify — over the repository
and the LogSourceProvider adapter registry. ``verify`` resolves the per-kind
adapter config (for S3, the assume-role creds come from the referenced AWS
connection) and probes reachability via ``LogSourcePort.verify``, then records
the outcome on the row. No ORM/SDK here beyond the injected collaborators.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class LogSourceConfigError(Exception):
    """The source's config can't be resolved into an adapter config (e.g. an S3
    source pointing at a missing AWS connection)."""


@dataclass
class LogSourceService:
    _repo: Any
    _provider: Any

    # ── Reads ────────────────────────────────────────────────────────────

    def list_sources(self, workspace_id):
        return self._repo.list_for_workspace(workspace_id)

    def get_source(self, workspace_id, source_id):
        return self._repo.get(workspace_id, source_id)

    # ── Writes ───────────────────────────────────────────────────────────

    def create_source(self, *, workspace_id, kind: str, name: str, config: dict):
        source = self._repo.create(
            workspace_id=workspace_id,
            kind=kind,
            name=name or f"{kind} source",
            config=config,
        )
        logger.info("log_source_created source_id=%s workspace_id=%s kind=%s", source.id, workspace_id, kind)
        return source

    def update_source(self, source, *, name=None, config=None, status=None):
        return self._repo.update(source, name=name, config=config, status=status)

    def delete_source(self, source) -> None:
        logger.info("log_source_deleted source_id=%s workspace_id=%s", source.id, source.workspace_id)
        self._repo.delete(source)

    # ── Verify ───────────────────────────────────────────────────────────

    def verify_source(self, source):
        """Probe the source's reachability and record the outcome. Success flips
        it ACTIVE (so the ingest pipeline starts reading it); failure marks ERROR
        with a scrubbed reason. Never raises for an expected config/probe failure.
        """
        try:
            config = self._adapter_config(source)
        except LogSourceConfigError as exc:
            return self._repo.mark_error(source, str(exc))

        health = self._provider.get(source.kind).verify(config)
        if health.ok:
            return self._repo.mark_verified(source)
        return self._repo.mark_error(source, health.detail or "Verification failed.")

    # ── internals ────────────────────────────────────────────────────────

    def _adapter_config(self, source) -> dict:
        """Resolve a stored source into a full adapter config. S3 needs the
        assume-role identity from its referenced AWS connection; other kinds carry
        self-contained config (3P secrets resolved via ``secret_ref`` in a later
        phase)."""
        from infrastructure.persistence.integrations.models import WorkspaceLogSource

        if source.kind == WorkspaceLogSource.Kind.S3:
            from components.integrations.application.log_ingest_service import s3_adapter_config
            from infrastructure.persistence.integrations.models import AwsOrganizationConnection

            conn_id = str((source.config or {}).get("aws_connection_id") or "")
            conn = (
                AwsOrganizationConnection.objects.filter(id=conn_id, workspace_id=source.workspace_id).first()
                if conn_id
                else None
            )
            if conn is None:
                raise LogSourceConfigError("S3 log source references a missing AWS connection.")
            return s3_adapter_config(conn, source)

        config = dict(source.config or {})
        config["source_id"] = str(source.id)
        return config
