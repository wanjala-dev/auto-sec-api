from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileEditRequest:
    """Input DTO for PATCH /profile/<uuid>/ endpoint.

    Used to update user profile details like title, bio, location, etc.
    All fields are optional for partial updates.
    """
    title: str | None = None
    dob: str | None = None
    address: str | None = None
    about: str | None = None
    country: dict | None = None
    zip: str | None = None
    photo_url: str | None = None
    banner_photo_url: str | None = None
    city: str | None = None
    name: str | None = None
    active_workspace_id: str | None = None
    active_team_id: str | None = None
