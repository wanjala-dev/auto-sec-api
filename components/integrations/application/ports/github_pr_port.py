"""Port for the GitHub draft-PR remediation surface (Explicit Architecture).

Defines exactly the operations the ``open_draft_pr`` use case needs — fetch
the default branch, read a file, create a branch, commit one file, open a
DRAFT pull request. Shaped to fit the application core, not to mirror the
GitHub API. The concrete adapter lives in
``components/integrations/infrastructure/adapters/github_pr_adapter.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


class GitHubApiError(RuntimeError):
    """A GitHub API call failed. Never swallowed — carries the HTTP status and
    a truncated response detail (never the token)."""

    def __init__(self, message: str, *, status_code: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


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
    """An opened draft pull request."""

    url: str
    number: int
    repo: str
    head: str
    base: str


class GitHubPrPort(ABC):
    """Driving-side contract for opening a draft PR against an allowlisted repo."""

    @abstractmethod
    def get_default_branch(self, repo: str) -> DefaultBranch:
        """Return the default branch name + head SHA for ``owner/repo``."""

    @abstractmethod
    def get_file(self, repo: str, path: str, ref: str) -> RepoFile:
        """Return the decoded content + blob SHA of ``path`` at ``ref``."""

    @abstractmethod
    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        """Create ``refs/heads/<branch>`` pointing at ``from_sha``."""

    @abstractmethod
    def commit_file(
        self, repo: str, branch: str, path: str, new_content: str, message: str, file_sha: str
    ) -> CommittedFile:
        """Commit ``new_content`` to ``path`` on ``branch`` (contents API)."""

    @abstractmethod
    def open_draft_pr(self, repo: str, head: str, base: str, title: str, body: str) -> DraftPullRequest:
        """Open a DRAFT pull request ``head`` → ``base``."""
