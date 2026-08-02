"""Check whether a remediation draft PR actually merged (ADR 0012 P4a).

The integrations context owns VCS access, so it owns the *question* "did this PR
merge?" — the remediation reconciler must not reach into a code host itself. This
use case is that surface: given a workspace and a draft-PR URL, it resolves the
workspace's ``VcsConnection``, decrypts its token, resolves the provider adapter,
and reads the PR's live state via :meth:`VcsPort.get_pull_request` — a real host
read, never a stored/blind flag.

Consent boundary: the PR's ``owner/repo`` must be on the resolving connection's
``repo_allowlist``. A URL pointing at a repo the operator never allowlisted is
refused (``allowed=False``) — the reconciler treats that exactly like "cannot
confirm merged" and skips, so a spoofed URL can never drive a corpus write.

Returns a small :class:`PullRequestMergeStatus` DTO. Any expected failure
(no connection, unparseable URL, repo not allowlisted, host API error) resolves
to ``merged=False`` with a scrubbed reason — this is a read used to *gate* a
corpus write, so it must fail closed and never crash the reconciler.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from components.integrations.application.ports.vcs_port import VcsApiError, VcsPort

logger = logging.getLogger(__name__)

# Matches ".../{owner}/{repo}/pull/{number}" (GitHub) or ".../merge_requests/{n}"
# (GitLab) tail of a PR/MR URL. Group 1 = "owner/repo", group 2 = number.
_PR_URL_RE = re.compile(r"[:/]([^/:]+/[^/]+)/(?:pull|pulls|merge_requests)/(\d+)(?:[/?#]|$)")


@dataclass(frozen=True)
class PullRequestMergeStatus:
    """The reconciler-facing answer: did the draft PR merge (and may we trust it)?"""

    merged: bool
    # False when the URL couldn't be resolved to an allowlisted, readable PR — the
    # reconciler treats allowed=False identically to merged=False (skip), but the
    # split lets callers log *why*.
    allowed: bool
    repo: str = ""
    pr_number: int = 0
    state: str = ""
    merged_at: str = ""
    reason: str = ""


def parse_pr_url(pr_url: str) -> tuple[str, int] | None:
    """Extract ``(owner/repo, number)`` from a PR/MR URL, or ``None`` if it doesn't
    match the expected shape. Kept module-level + pure so the reconciler test can
    assert URL handling without a host."""
    if not pr_url:
        return None
    match = _PR_URL_RE.search(pr_url.strip())
    if not match:
        return None
    return match.group(1), int(match.group(2))


class CheckPullRequestMergedUseCase:
    def __init__(
        self,
        *,
        resolve_connection: Callable[[str], object | None],
        decrypt: Callable[[str], str],
        resolve_adapter: Callable[[str, str], VcsPort],
    ) -> None:
        # resolve_connection: (workspace_id) -> VcsConnection-like | None
        # decrypt: (ciphertext) -> plaintext token
        # resolve_adapter: (provider, token) -> VcsPort
        self._resolve_connection = resolve_connection
        self._decrypt = decrypt
        self._resolve_adapter = resolve_adapter

    def execute(self, *, workspace_id: str, pr_url: str) -> PullRequestMergeStatus:
        parsed = parse_pr_url(pr_url)
        if parsed is None:
            return PullRequestMergeStatus(merged=False, allowed=False, reason="unparseable_pr_url")
        repo, number = parsed

        connection = self._resolve_connection(workspace_id)
        if connection is None:
            return PullRequestMergeStatus(
                merged=False, allowed=False, repo=repo, pr_number=number, reason="no_vcs_connection"
            )

        # Consent boundary: the PR must be on this connection's allowlist. A URL for
        # a repo the operator never allowlisted is refused before any host call.
        allowlist = [r for r in (getattr(connection, "repo_allowlist", None) or []) if isinstance(r, str) and r.strip()]
        if repo not in allowlist:
            return PullRequestMergeStatus(
                merged=False, allowed=False, repo=repo, pr_number=number, reason="repo_not_allowlisted"
            )

        token = self._decrypt(getattr(connection, "token_ciphertext", "") or "")
        if not token:
            return PullRequestMergeStatus(merged=False, allowed=False, repo=repo, pr_number=number, reason="no_token")

        try:
            adapter = self._resolve_adapter(getattr(connection, "provider", ""), token)
            state = adapter.get_pull_request(repo, number)
        except VcsApiError as exc:
            # A host API failure (incl. 404 = PR gone/inaccessible) means we cannot
            # confirm merged → fail closed, but keep the error visible (scrubbed).
            logger.info(
                "check_pr_merged_api_error workspace_id=%s repo=%s pr=%s status=%s",
                workspace_id,
                repo,
                number,
                exc.status_code,
            )
            return PullRequestMergeStatus(
                merged=False, allowed=True, repo=repo, pr_number=number, reason="host_api_error"
            )

        return PullRequestMergeStatus(
            merged=bool(state.merged),
            allowed=True,
            repo=repo,
            pr_number=number,
            state=state.state,
            merged_at=state.merged_at,
            reason="merged" if state.merged else "not_merged",
        )
