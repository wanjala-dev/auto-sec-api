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
def read_repo_file(*, workspace_id, repo: str, path: str, ref: str = "") -> str | None:
    """Read ONE file from an allowlisted repo, or ``None`` (fail closed).

    The SAST triage advisor's read seam (ADR 0019 P2): ground the fix suggestion
    on the REAL file content at the scanned commit. Same consent boundary as the
    scan vend — a repo off the ``repo_allowlist`` never reaches the VCS API, and a
    traversal-shaped path is refused before any call. Every failure degrades to
    ``None`` (a suggestion is an enhancement, never a gate on triage).
    """
    from components.integrations.application.ports.vcs_port import VcsApiError
    from components.integrations.application.providers.secret_envelope_provider import decrypt_secret
    from components.integrations.application.providers.vcs_provider import get_vcs_adapter

    clean_path = (path or "").strip().lstrip("/")
    # Traversal guard (same rule as ``resolve_repo_path``): an absolute path or a
    # ``.``/``..`` segment could climb out of the repo-scoped contents URL.
    normalized = clean_path.replace("\\", "/")
    if not clean_path or any(seg in (".", "..") for seg in normalized.split("/")):
        return None
    connection = resolve_scan_connection(workspace_id, repo)
    if connection is None:
        logger.warning("vcs_file_read_denied workspace_id=%s repo=%s (not allowlisted)", workspace_id, repo)
        return None
    token = decrypt_secret(connection.token_ciphertext)
    if not token:
        return None
    adapter = get_vcs_adapter(connection.provider, token)
    try:
        # ``ref`` is REQUIRED by the port (an implicit "whatever HEAD is now" read
        # would silently ground a fix on different content than was scanned). A
        # caller with no scanned SHA falls back to the resolved default branch.
        resolved_ref = ref or adapter.get_default_branch(repo).name
        return adapter.get_file(repo, clean_path, ref=resolved_ref).content
    except VcsApiError:
        logger.warning("vcs_file_read_failed workspace_id=%s repo=%s path=%s", workspace_id, repo, clean_path)
        return None


def _consented_adapter(workspace_id, repo: str):
    """The (adapter, connection) pair for an allowlisted repo, or ``(None, None)``.

    The shared front half of every read below: resolve the consent row, refuse a
    repo that is not on the allowlist, decrypt the token. Extracted so a new read
    capability cannot accidentally ship without the allowlist check — the check is
    not something each function remembers to do, it is the only way to get an
    adapter at all.
    """
    from components.integrations.application.providers.secret_envelope_provider import decrypt_secret
    from components.integrations.application.providers.vcs_provider import get_vcs_adapter

    connection = resolve_scan_connection(workspace_id, repo)
    if connection is None:
        logger.warning("vcs_read_denied workspace_id=%s repo=%s (not allowlisted)", workspace_id, repo)
        return None, None
    token = decrypt_secret(connection.token_ciphertext)
    if not token:
        return None, None
    return get_vcs_adapter(connection.provider, token), connection


def list_repo_tree(*, workspace_id, repo: str, ref: str = "", limit: int = 400) -> list[str]:
    """Every file path in an allowlisted repo, or ``[]`` (fail closed).

    Lets the specialist see the project's shape before guessing at paths. Capped
    because the whole tree of a large repo would blow the agent's context window
    for no benefit — a truncated listing is logged so a caller can tell "not
    there" from "not shown".
    """
    from components.integrations.application.ports.vcs_port import VcsApiError

    adapter, _ = _consented_adapter(workspace_id, repo)
    if adapter is None:
        return []
    try:
        resolved_ref = ref or adapter.get_default_branch(repo).name
        paths = adapter.list_tree(repo, resolved_ref)
    except VcsApiError:
        logger.warning("vcs_tree_read_failed workspace_id=%s repo=%s", workspace_id, repo)
        return []
    if len(paths) > limit:
        logger.info("vcs_tree_truncated workspace_id=%s repo=%s shown=%s of=%s", workspace_id, repo, limit, len(paths))
    return paths[:limit]


def search_repo(*, workspace_id, repo: str, query: str, limit: int = 20) -> list[dict]:
    """Search an allowlisted repo's code, or ``[]`` (fail closed).

    The capability whose absence produced PR #326's invented ``fetch_jwks_key``:
    asked to verify a JWT signature, the advisor had no way to find where that
    project keeps its issuer key, so it made one up. Returns plain dicts because
    the consumer is an LLM tool that serialises to JSON.
    """
    from components.integrations.application.ports.vcs_port import VcsApiError

    if not (query or "").strip():
        return []
    adapter, _ = _consented_adapter(workspace_id, repo)
    if adapter is None:
        return []
    try:
        hits = adapter.search_code(repo, query.strip(), limit=limit)
    except VcsApiError:
        # Includes providers with no code-search API — "cannot search here" is a
        # capability gap the agent should route around, not a run-ending error.
        logger.warning("vcs_code_search_failed workspace_id=%s repo=%s", workspace_id, repo)
        return []
    return [{"path": h.path, "line_number": h.line_number, "line": h.line} for h in hits]


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
