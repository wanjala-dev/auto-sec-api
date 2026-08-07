"""Read-only repo access for SAST scans — the infrastructure half (ADR 0019 D2/D6).

Implementation behind ``application/providers/vcs_scan_access_provider`` (the
published seam other pillars call). Lives in infrastructure because it touches
the ORM, the secret envelope, and Django's ``sensitive_variables`` scrubbing —
none of which belong in the application layer.
"""

from __future__ import annotations

import logging

from django.views.decorators.debug import sensitive_variables

logger = logging.getLogger(__name__)


def resolve_scan_connection(workspace_id, repo: str, connection_id: str | None = None):
    """Return the ``VcsConnection`` allowed to scan ``repo``, or ``None`` (fail closed).

    With ``connection_id`` the row must belong to the workspace AND allowlist the
    repo; without it, the workspace's most recent connection whose allowlist
    carries the repo wins.
    """
    from infrastructure.persistence.integrations.models import VcsConnection

    queryset = VcsConnection.objects.filter(workspace_id=workspace_id).order_by("-created_at")
    if connection_id:
        queryset = queryset.filter(id=connection_id)
    for connection in queryset:
        if repo in (connection.repo_allowlist or []):
            return connection
    return None


def list_scannable_repos(workspace_id) -> list[tuple[str, str]]:
    """Every (repo, connection_id) the workspace has consented to scan.

    CONNECTED connections only; a repo listed on two connections dedupes to the
    most recent one (the same most-recent-wins rule as ``resolve_scan_connection``).
    """
    from infrastructure.persistence.integrations.models import VcsConnection

    seen: set[str] = set()
    targets: list[tuple[str, str]] = []
    connections = VcsConnection.objects.filter(
        workspace_id=workspace_id, status=VcsConnection.Status.CONNECTED
    ).order_by("-created_at")
    for connection in connections:
        for repo in connection.repo_allowlist or []:
            if isinstance(repo, str) and repo.strip() and repo not in seen:
                seen.add(repo)
                targets.append((repo, str(connection.id)))
    return targets


@sensitive_variables("token")
def vend_repo_read_access(*, workspace_id, repo: str, connection_id: str | None = None) -> dict | None:
    """Vend the scan-Job credential envelope for ``repo``, or ``None`` (fail closed).

    The envelope — ``{"provider", "repo", "token", "commit_sha", "archive_url"}`` —
    is built at scan time so the token's exposure window is the scan itself and the
    SHA is the branch head *now*. Every failure path logs and returns ``None``; the
    scan task then fails loud on the missing credentials rather than scanning
    without consent.
    """
    from components.integrations.application.providers.secret_envelope_provider import decrypt_secret
    from components.integrations.application.providers.vcs_provider import get_vcs_adapter

    connection = resolve_scan_connection(workspace_id, repo, connection_id)
    if connection is None:
        logger.warning(
            "vcs_scan_access_denied workspace_id=%s repo=%s connection_id=%s (not allowlisted)",
            workspace_id,
            repo,
            connection_id,
        )
        return None

    token = decrypt_secret(connection.token_ciphertext)
    if not token:
        logger.warning("vcs_scan_access_no_token workspace_id=%s connection_id=%s", workspace_id, connection.id)
        return None

    adapter = get_vcs_adapter(connection.provider, token)
    branch = adapter.get_default_branch(repo)
    return {
        "provider": connection.provider,
        "repo": repo,
        "token": token,
        "commit_sha": branch.head_sha,
        "archive_url": adapter.get_archive_url(repo, branch.head_sha),
    }
