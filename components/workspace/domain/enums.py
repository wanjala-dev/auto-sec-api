"""Canonical domain enums for the workspace bounded context.

Domain-layer code MUST import from here, never from ORM models.
The ORM ``TextChoices`` enums stay in ``apps/`` for Django infrastructure
needs (e.g. migration ``choices=`` parameters).
"""

from __future__ import annotations


class WorkspaceStatus:
    ACTIVE = "active"
    INACTIVE = "inactive"
    _ALL = {ACTIVE, INACTIVE}

    @classmethod
    def validate(cls, value: str) -> str:
        if value not in cls._ALL:
            raise ValueError(f"Invalid workspace status: {value!r}")
        return value


class WorkspacePrivacy:
    PUBLIC = "public"
    PRIVATE = "private"
    _ALL = {PUBLIC, PRIVATE}
