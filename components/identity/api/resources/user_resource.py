from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class UserResource:
    """Output DTO for user detail endpoints.

    Represents core user information returned by user detail/list endpoints.
    """
    id: str
    email: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    is_onboard_complete: bool | None = None
    is_contributor: bool | None = None
    created_at: str | None = None
    updated_at: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class UserProfileResource:
    """Output DTO for user profile details.

    Represents detailed profile information from UserProfile model.
    """
    title: str | None = None
    name: str | None = None
    dob: str | None = None
    address: str | None = None
    about: str | None = None
    city: str | None = None
    zip: str | None = None
    photo_url: str | None = None
    banner_photo_url: str | None = None
    country: dict | None = None
    followers_count: int = 0
    following_count: int = 0
    active_workspace_id: str | None = None
    active_team_id: str | None = None
    active_workspace: dict | None = None


@dataclass(frozen=True)
class UserDetailResource:
    """Output DTO for full user detail endpoint responses.

    Combines user and profile data for comprehensive detail views.
    """
    user: UserResource
    profile: UserProfileResource | None = None
    contributor_profile: dict | None = None
    workspaces: list[dict] | None = None
    teams: list[dict] | None = None
    sectors: list[dict] | None = None


@dataclass(frozen=True)
class UserSummaryResource:
    """Output DTO for lightweight user summary responses.

    Used for post-login hydration and summary endpoints. Excludes
    nested collections to keep payload minimal.
    """
    id: str
    email: str
    username: str
    first_name: str | None = None
    last_name: str | None = None
    is_onboard_complete: bool | None = None
    is_contributor: bool | None = None
    two_factor_enabled: bool | None = None
    two_factor_confirmed_at: str | None = None
    profile: UserProfileResource | None = None
    sector_ids: list[str] | None = None
