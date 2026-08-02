"""Port for the VCS draft-PR remediation surface (Explicit Architecture, ADR 0010).

Defines exactly the operations the ``open_draft_pr`` use case needs — probe
reachability, fetch the default branch, read a file, create a branch, commit one
file, open a DRAFT pull request. Shaped to fit the application core, not to mirror
any one provider's API. Concrete adapters (GitHub today; GitLab/Bitbucket behind
flags) live in ``components/integrations/infrastructure/adapters/vcs/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class VcsApiError(RuntimeError):
    """A VCS provider API call failed. Never swallowed — carries the HTTP status and
    a truncated response detail (never the token)."""

    def __init__(self, message: str, *, status_code: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class VcsHealth:
    """The result of a reachability/access probe (mirrors ``LogSourceHealth``)."""

    ok: bool
    detail: str = ""  # human-readable reason on failure (never a secret)


@dataclass(frozen=True)
class DefaultBranch:
    """The repo's default branch and its current head commit SHA."""

    name: str
    head_sha: str


@dataclass(frozen=True)
class RepoFile:
    """A file's decoded content plus the blob SHA needed to update it."""

    path: str
    content: str
    sha: str


@dataclass(frozen=True)
class CommittedFile:
    """The result of committing one file to a branch."""

    path: str
    commit_sha: str


@dataclass(frozen=True)
class DraftPullRequest:
    """An opened draft pull request (a GitLab *merge request* / Bitbucket *pull
    request* is the adapter's mapping onto this shape)."""

    url: str
    number: int
    repo: str
    head: str
    base: str


@dataclass(frozen=True)
class PullRequestState:
    """The live state of a pull request, read back from the host (ADR 0012 P4a).

    Shaped to the remediation-reconciler's single question — *did this fix actually
    land?* — not to any one host's PR object. ``merged`` is the load-bearing fact:
    the remediation entry-gate treats "applied" as *merged*, never merely "open" or
    "closed-without-merge". ``state`` is the host's coarse lifecycle token
    (``"open"`` / ``"closed"``) surfaced for logging/branching; ``merged_at`` is the
    ISO-8601 merge timestamp (empty when unmerged). A closed-but-unmerged PR is
    ``merged=False`` — the fix was abandoned, so nothing is captured."""

    merged: bool
    state: str
    merged_at: str = ""


class VcsPort(ABC):
    """Driving-side contract for opening a draft PR against an allowlisted repo on a
    code host (GitHub / GitLab / Bitbucket)."""

    @abstractmethod
    def verify(self, repo: str | None = None) -> VcsHealth:
        """Probe reachability + token validity; if ``repo`` is given, confirm the
        connection can access it. Returns a :class:`VcsHealth` — never raises for an
        expected auth/access failure (the detail is scrubbed of secrets)."""

    @abstractmethod
    def get_default_branch(self, repo: str) -> DefaultBranch:
        """Return the default branch name + head SHA for ``owner/repo``."""

    @abstractmethod
    def get_file(self, repo: str, path: str, ref: str) -> RepoFile:
        """Return the decoded content + blob SHA of ``path`` at ``ref``."""

    @abstractmethod
    def list_tree(self, repo: str, ref: str) -> list[str]:
        """Return every blob (file) path in ``repo`` at ``ref``, recursively.

        Used by monorepo path resolution to locate a runtime-relative source file
        that lives under a repo subdirectory. Directory/submodule entries are
        excluded — only ``type == 'blob'`` paths are returned."""

    @abstractmethod
    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        """Create ``refs/heads/<branch>`` pointing at ``from_sha``."""

    @abstractmethod
    def commit_file(
        self,
        repo: str,
        branch: str,
        path: str,
        new_content: str,
        message: str,
        file_sha: str,
        author: dict | None = None,
    ) -> CommittedFile:
        """Commit ``new_content`` to ``path`` on ``branch`` (contents API).

        ``author`` — optional ``{"name", "email"}``. When supplied, the adapter stamps
        both author and committer so the host attributes the commit to that identity;
        when ``None`` (default), the host attributes it to the token/PAT owner."""

    @abstractmethod
    def open_draft_pr(self, repo: str, head: str, base: str, title: str, body: str) -> DraftPullRequest:
        """Open a DRAFT pull request ``head`` → ``base``."""

    @abstractmethod
    def get_pull_request(self, repo: str, pr_ref: int | str) -> PullRequestState:
        """Read back the live state of pull request ``pr_ref`` in ``repo``.

        ``pr_ref`` is the host's PR number (an ``int`` or its string form). Returns
        a :class:`PullRequestState` whose ``merged`` flag is verified against the
        host (a real read, not a stored/blind flag) — the remediation reconciler
        (ADR 0012 P4a) uses it to confirm a remediation draft PR actually *merged*
        before its finding may enter the vetted corpus. Raises :class:`VcsApiError`
        on an API failure (never swallowed); a missing PR (404) surfaces as such so
        the caller can treat it as "cannot confirm merged" and skip."""
