"""Pure domain entity for a user profile in the Identity bounded context."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class UserProfileEntity:
    """Immutable snapshot of a user's profile information."""

    user_id: UUID
    active_team_id: int
    active_workspace_id: UUID | None
    title: str
    about: str | None
    address: str
    city: str | None
    zip: str | None
    country_id: int | None
    photo_url: str | None
    banner_photo_url: str | None
    name: str | None
    dob: datetime.date | None = None
    followers_count: int = 0
    following_count: int = 0


@dataclass(frozen=True)
class ContributorProfileEntity:
    """Immutable snapshot of a contributor profile."""

    user_id: UUID
    preferred_location_ids: tuple[int, ...] = ()
    contribution_means_ids: tuple[int, ...] = ()
