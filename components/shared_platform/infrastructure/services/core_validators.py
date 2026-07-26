"""Shared validators for request payloads.

The canonical implementation now lives in the shared kernel
(``components.shared_kernel.infrastructure.support.validators``); re-exported here
for backward compatibility with existing shared_platform consumers.
"""

from __future__ import annotations

from components.shared_kernel.infrastructure.support.validators import ensure_uuid

__all__ = ["ensure_uuid"]
