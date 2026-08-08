"""Repo-reference validation — the untrusted-input gate for SAST scans (ADR 0019).

A code-security scan target is an ``owner/repo`` string (the same shape as the
``VcsConnection.repo_allowlist`` entries, ADR 0010). It reaches a scan-Job script
as a positional parameter and the VCS API as a URL path segment, so it is
validated strictly here — mirroring ``container_security.image_reference`` for
image refs. Anything with shell metacharacters, path traversal, flags, or
whitespace fails loud.
"""

from __future__ import annotations

import re

_MAX_LENGTH = 200

# owner/repo — one slash, conservative charset per GitHub/GitLab/Bitbucket naming.
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{7,64}$")


class InvalidRepoReferenceError(ValueError):
    """The supplied repo reference is not a safe ``owner/repo`` string."""


def validate_repo_reference(value: str) -> str:
    """Validate and return a canonical ``owner/repo`` reference. Fail loud otherwise."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise InvalidRepoReferenceError("Repo reference cannot be empty")
    if len(cleaned) > _MAX_LENGTH:
        raise InvalidRepoReferenceError(f"Repo reference too long ({len(cleaned)} > {_MAX_LENGTH})")
    if ".." in cleaned:
        raise InvalidRepoReferenceError(f"Repo reference must not contain '..': {cleaned!r}")
    if not _REPO_RE.match(cleaned):
        raise InvalidRepoReferenceError(f"Not a valid owner/repo reference: {cleaned!r}")
    return cleaned


def validate_commit_sha(value: str) -> str:
    """Validate a resolved git commit SHA (lowercase hex). Fail loud otherwise."""
    cleaned = (value or "").strip().lower()
    if not _COMMIT_SHA_RE.match(cleaned):
        raise InvalidRepoReferenceError(f"Not a valid commit SHA: {value!r}")
    return cleaned
