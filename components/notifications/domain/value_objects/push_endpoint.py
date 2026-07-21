"""Push endpoint identity derivation.

The registry keys device rows on ``sha256(endpoint)`` (hex) instead of the
raw endpoint URL: push-service endpoints are long (breaking unique-index
limits on some backends) and privacy-sensitive (they grant send access), so
the hash is the stable, index-friendly identity used for upsert and revoke.

Pure function — no framework imports (domain layer).
"""

from __future__ import annotations

import hashlib

from components.notifications.domain.errors import NotificationValidationError

ENDPOINT_HASH_LENGTH = 64  # sha256 hex digest


def derive_endpoint_hash(endpoint: str) -> str:
    """Return the canonical sha256 hex identity for a push endpoint.

    Leading/trailing whitespace is stripped before hashing so accidental
    copy-paste padding cannot register the same device twice. Empty (or
    whitespace-only) endpoints are a caller bug — raise, don't hash.
    """
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise NotificationValidationError("endpoint is required to derive an endpoint hash")
    return hashlib.sha256(endpoint.strip().encode("utf-8")).hexdigest()
