from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class UserPatchRequest:
    """Input DTO for PATCH /edit/<uuid>/ endpoint.

    Used to update user profile, contributor profile, and sector associations.
    All fields are optional for partial updates.
    """
    username: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_onboard_complete: bool | None = None
    is_contributor: bool | None = None
    profile: dict | None = None
    contributor_profile: dict | None = None
    sector_ids: list[str] | None = None
