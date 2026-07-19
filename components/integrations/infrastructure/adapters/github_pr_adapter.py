"""GitHub REST adapter for the draft-PR port (plain ``requests``).

Implements :class:`GitHubPrPort` against ``https://api.github.com`` with a
fine-grained PAT (Phase A). Every non-2xx response raises
:class:`GitHubApiError` with the status and a truncated response body — never
swallowed, and the token never appears in logs, errors, or exception state.
"""

from __future__ import annotations

import base64
import logging

import requests
from django.views.decorators.debug import sensitive_variables

from components.integrations.application.ports.github_pr_port import (
    CommittedFile,
    DefaultBranch,
    DraftPullRequest,
    GitHubApiError,
    GitHubPrPort,
    RepoFile,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.github.com"
_TIMEOUT_SECONDS = 20
_API_VERSION = "2022-11-28"


class GitHubPrAdapter(GitHubPrPort):
    """Concrete GitHub REST implementation of the draft-PR port."""

    @sensitive_variables("token")
    def __init__(self, token: str, *, base_url: str = _BASE_URL) -> None:
        if not token:
            raise GitHubApiError("A GitHub token is required.", status_code=None)
        self._token = token
        self._base_url = base_url.rstrip("/")

    # ── HTTP core ─────────────────────────────────────────────────────

    @sensitive_variables("headers")
    def _request(self, method: str, path: str, *, json_body: dict | None = None, params: dict | None = None) -> dict:
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
        }
        try:
            response = requests.request(
                method, url, headers=headers, json=json_body, params=params, timeout=_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            logger.exception("github_api_request_failed method=%s path=%s", method, path)
            raise GitHubApiError(f"GitHub request failed: {method} {path}", status_code=None) from exc
        if response.status_code >= 300:
            detail = (response.text or "")[:500]
            logger.error(
                "github_api_error method=%s path=%s status=%s detail=%s",
                method,
                path,
                response.status_code,
                detail[:200],
            )
            raise GitHubApiError(
                f"GitHub API {method} {path} returned {response.status_code}",
                status_code=response.status_code,
                detail=detail,
            )
        if response.status_code == 204 or not (response.text or "").strip():
            return {}
        return response.json()

    # ── Port operations ───────────────────────────────────────────────

    def get_default_branch(self, repo: str) -> DefaultBranch:
        repo_data = self._request("GET", f"/repos/{repo}")
        branch = repo_data.get("default_branch") or "main"
        ref = self._request("GET", f"/repos/{repo}/git/ref/heads/{branch}")
        sha = (ref.get("object") or {}).get("sha") or ""
        if not sha:
            raise GitHubApiError(f"Could not resolve head SHA for {repo}@{branch}", status_code=None)
        return DefaultBranch(name=branch, head_sha=sha)

    def get_file(self, repo: str, path: str, ref: str) -> RepoFile:
        data = self._request("GET", f"/repos/{repo}/contents/{path}", params={"ref": ref})
        if isinstance(data, list):
            raise GitHubApiError(f"{path} is a directory, not a file, in {repo}", status_code=None)
        raw = data.get("content") or ""
        try:
            content = base64.b64decode(raw).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubApiError(f"Could not decode {path} from {repo}", status_code=None) from exc
        return RepoFile(path=path, content=content, sha=data.get("sha") or "")

    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        self._request(
            "POST",
            f"/repos/{repo}/git/refs",
            json_body={"ref": f"refs/heads/{branch}", "sha": from_sha},
        )

    def commit_file(
        self, repo: str, branch: str, path: str, new_content: str, message: str, file_sha: str
    ) -> CommittedFile:
        encoded = base64.b64encode(new_content.encode("utf-8")).decode("ascii")
        data = self._request(
            "PUT",
            f"/repos/{repo}/contents/{path}",
            json_body={
                "message": message,
                "content": encoded,
                "branch": branch,
                "sha": file_sha,
            },
        )
        commit_sha = (data.get("commit") or {}).get("sha") or ""
        return CommittedFile(path=path, commit_sha=commit_sha)

    def open_draft_pr(self, repo: str, head: str, base: str, title: str, body: str) -> DraftPullRequest:
        data = self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json_body={"title": title, "head": head, "base": base, "body": body, "draft": True},
        )
        url = data.get("html_url") or ""
        number = int(data.get("number") or 0)
        if not url:
            raise GitHubApiError(f"GitHub created a PR on {repo} but returned no URL", status_code=None)
        return DraftPullRequest(url=url, number=number, repo=repo, head=head, base=base)
