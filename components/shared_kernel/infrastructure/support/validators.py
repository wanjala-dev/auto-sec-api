"""Shared request-payload validators (canonical home).

``ensure_uuid`` lives here in the shared kernel — the innermost shared layer — so
every context (including shared_platform) depends inward on it rather than the
kernel reaching outward. shared_platform's ``core_validators`` re-exports it for
backward compatibility.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from rest_framework.exceptions import ValidationError


def ensure_uuid(value: Optional[str], *, field_name: str = "id", required: bool = True) -> Optional[UUID]:
    """Normalize and validate a UUID coming from request parameters.

    ``required=False`` returns ``None`` for missing/blank input instead of raising.
    Raises DRF ``ValidationError`` on a missing-required or malformed value.
    """
    if value in (None, ""):
        if required:
            raise ValidationError({field_name: ["This field is required."]})
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise ValidationError({field_name: ["Must be a valid UUID."]})
