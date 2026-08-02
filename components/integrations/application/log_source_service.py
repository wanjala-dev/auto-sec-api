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

# Source-kind identifiers (mirror ``WorkspaceLogSource.Kind`` values, which are the
# same strings the ``LogSourcePort`` adapters register under). Kept as plain
# constants here so this application service never imports the ORM enum.
_KIND_S3 = "s3"
_KIND_CLOUDWATCH = "cloudwatch"


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

        try:
            adapter = self._provider.get(source.kind)
        except Exception as exc:  # UnsupportedLogSourceError — adapter not registered (e.g. flag off)
            return self._repo.mark_error(source, f"{source.kind} log source is not available: {exc}")

        health = adapter.verify(config)
        if health.ok:
            return self._repo.mark_verified(source)
        return self._repo.mark_error(source, health.detail or "Verification failed.")

    # ── internals ────────────────────────────────────────────────────────

    def _adapter_config(self, source) -> dict:
        """Resolve a stored source into a full adapter config. AWS-backed sources
        (S3, CloudWatch) take their assume-role identity from the referenced AWS
        connection; other kinds carry self-contained config (3P secrets resolved via
        ``secret_ref`` in a later phase)."""
        if source.kind == _KIND_S3:
            from components.integrations.application.log_ingest_service import s3_adapter_config

            return s3_adapter_config(self._connection_for(source), source)

        if source.kind == _KIND_CLOUDWATCH:
            conn = self._connection_for(source)
            config = dict(source.config or {})
            config.update(
                {
                    "management_account_id": conn.management_account_id,
                    "role_name": conn.role_name,
                    "external_id": conn.external_id,
                    "source_id": str(source.id),
                }
            )
            return config

        config = dict(source.config or {})
        config["source_id"] = str(source.id)
        return config

    def _connection_for(self, source):
        """Resolve the AWS connection an S3/CloudWatch source reads through — the
        one place this lookup lives (DRY). The ORM lookup goes through the
        ``LogSourceRepository`` so this service stays ORM-free."""
        conn = self._repo.find_connection_for_source(source)
        if conn is None:
            raise LogSourceConfigError(f"{source.kind} log source references a missing AWS connection.")
        return conn
