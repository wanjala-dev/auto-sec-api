"""Validate an untrusted container image reference (ADR 0006 D5).

The one gate between a tenant-supplied image ref and a scanner invocation. Even though
the ref is always passed after ``--`` (end-of-flags) into a fixed argv (no shell), we
validate it defensively because it also drives a registry pull:

- reject anything starting with ``-`` (arg/flag injection like ``--output=/etc/x``),
- enforce a strict OCI reference shape (``[registry[:port]/]repo[:tag][@sha256:digest]``),
- reject shell/whitespace metacharacters outright,
- optionally enforce a registry allowlist (a tenant's ECR) so a scan can't be pointed at
  the metadata endpoint / an attacker registry (SSRF / exfil).

Raises ``InvalidImageReferenceError`` on anything that isn't obviously safe — fail closed.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# A pragmatic OCI reference: optional registry host[:port]/, path segments, optional
# :tag and/or @sha256:<hex>. Intentionally conservative — reject rather than guess.
_REF_RE = re.compile(
    r"^"
    r"(?:(?P<registry>[a-z0-9.-]+(?::[0-9]+)?)/)?"  # optional registry[:port]/
    r"(?P<path>[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*)"  # repo path
    r"(?::(?P<tag>[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}))?"  # optional :tag
    r"(?:@sha256:(?P<digest>[a-f0-9]{64}))?"  # optional @sha256:digest
    r"$"
)

_MAX_LEN = 512


class InvalidImageReferenceError(ValueError):
    """A container image reference failed validation (rejected, fail-closed)."""


def validate_image_reference(ref: str, *, allowed_registries: Iterable[str] | None = None) -> str:
    """Return the ref unchanged if valid; else raise ``InvalidImageReferenceError``.

    ``allowed_registries`` (when given) is an allowlist of registry hosts; a ref whose
    registry isn't listed — including a ref with no registry (implicit Docker Hub) when an
    allowlist is set — is rejected.
    """
    if not isinstance(ref, str):
        raise InvalidImageReferenceError("image reference must be a string")
    cleaned = ref.strip()
    if not cleaned:
        raise InvalidImageReferenceError("image reference is empty")
    if len(cleaned) > _MAX_LEN:
        raise InvalidImageReferenceError("image reference too long")
    if cleaned.startswith("-"):
        # Would be parsed as a flag by the scanner CLI (arg injection).
        raise InvalidImageReferenceError("image reference may not start with '-'")
    if any(c.isspace() for c in cleaned) or any(c in cleaned for c in ";|&$`<>()\\'\"\n\r\t"):
        raise InvalidImageReferenceError("image reference contains illegal characters")

    match = _REF_RE.match(cleaned)
    if not match:
        raise InvalidImageReferenceError(f"malformed image reference: {cleaned!r}")

    if allowed_registries is not None:
        allow = {r.strip().lower() for r in allowed_registries if r.strip()}
        registry = (match.group("registry") or "").lower()
        if registry not in allow:
            raise InvalidImageReferenceError(f"registry {registry or '(docker hub)'!r} not in the allowlist")

    return cleaned
