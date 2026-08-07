"""Trigger one Opengrep scan of an allowlisted repo (ADR 0019 D3).

The trigger-time half of the consent gate: validate the ``owner/repo`` shape and
confirm the workspace's VcsConnection allowlists it (via the integrations seam)
BEFORE anything is enqueued — a fast, honest rejection instead of a queued scan
that fails at vend time. The scan-time vend re-checks the allowlist fail-closed
(``vcs_scan_access_provider``), so a race with an allowlist edit cannot scan an
unconsented repo.
"""

from __future__ import annotations

import logging

from components.code_security.domain.repo_reference import (
    InvalidRepoReferenceError,
    validate_repo_reference,
)

logger = logging.getLogger(__name__)

SOURCE = "code_security.opengrep"


class RepoScanRejected(Exception):
    """The scan request failed the trigger-time gate. ``code`` is the API error token."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class TriggerRepoScanUseCase:
    def prepare(self, *, workspace_id, repo: str, connection_id: str | None = None) -> dict:
        """Validate + gate, returning the ``dispatch_scan`` kwargs (no side effects)."""
        from components.integrations.application.providers.vcs_scan_access_provider import (
            resolve_scan_connection,
        )

        try:
            cleaned = validate_repo_reference(repo)
        except InvalidRepoReferenceError as exc:
            raise RepoScanRejected("invalid_repo", str(exc)) from exc

        connection = resolve_scan_connection(workspace_id, cleaned, connection_id)
        if connection is None:
            raise RepoScanRejected(
                "repo_not_allowlisted",
                f"{cleaned} is not on this workspace's VCS connection allowlist.",
            )
        return {
            "source": SOURCE,
            "workspace_id": str(workspace_id),
            "target_ref": cleaned,
            "connection_id": str(connection.id),
        }

    def execute(self, *, workspace_id, repo: str, connection_id: str | None = None) -> dict:
        """Gate + enqueue. Returns ``{"task_id", "repo", "source"}``."""
        from components.scanning.application.providers.scan_dispatch_provider import dispatch_scan

        kwargs = self.prepare(workspace_id=workspace_id, repo=repo, connection_id=connection_id)
        async_result = dispatch_scan(**kwargs)
        logger.info(
            "code_security_scan_dispatched workspace_id=%s repo=%s task_id=%s",
            workspace_id,
            kwargs["target_ref"],
            async_result.id,
        )
        return {"task_id": str(async_result.id), "repo": kwargs["target_ref"], "source": SOURCE}
