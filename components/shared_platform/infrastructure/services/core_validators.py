"""
Shared validators for request payloads.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from rest_framework.exceptions import ValidationError


def ensure_uuid(value: Optional[str], *, field_name: str = "id", required: bool = True) -> Optional[UUID]:
    """
    Normalize and validate UUID values coming from request parameters.

    Args:
        value: The raw value provided by the caller.
        field_name: Field label used in the validation error payload.
        required: When False, missing/blank values return None instead of raising.

    Returns:
        UUID: The parsed UUID instance or None when not required.

    Raises:
        ValidationError: If the value is missing (and required) or not a valid UUID string.
    """

    if value in (None, ""):
        if required:
            raise ValidationError({field_name: ["This field is required."]})
        return None

    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        raise ValidationError({field_name: ["Must be a valid UUID."]})
