"""ORM → domain entity mappers for the Identity bounded context.

These mappers live at the infrastructure boundary. They translate Django ORM
model instances into frozen domain entities so the application and domain
layers never depend on Django.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from components.identity.domain.entities.auth_audit_entity import AuthAuditEventEntity
from components.identity.domain.entities.invited_user_entity import InvitedUserEntity
from components.identity.domain.entities.user_entity import UserEntity
from components.identity.domain.entities.user_profile_entity import (
    ContributorProfileEntity,
    UserProfileEntity,
)

if TYPE_CHECKING:
    from infrastructure.persistence.users.models import (
        AuthAuditEvent,
        ContributorProfile,
        CustomUser,
        InvitedUser,
        UserProfile,
    )


def to_user_entity(user: CustomUser) -> UserEntity:
    return UserEntity(
        id=user.id,
        username=user.username,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        is_verified=user.is_verified,
        is_active=user.is_active,
        is_staff=user.is_staff,
        is_onboard_complete=user.is_onboard_complete,
        is_contributor=user.is_contributor,
        two_factor_enabled=user.two_factor_enabled,
        two_factor_confirmed_at=user.two_factor_confirmed_at,
        auth_provider=user.auth_provider,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def to_user_profile_entity(profile: UserProfile) -> UserProfileEntity:
    return UserProfileEntity(
        user_id=profile.user_id,
        active_team_id=profile.active_team_id,
        active_workspace_id=profile.active_workspace_id,
        title=profile.title,
        about=profile.about,
        address=profile.address,
        city=profile.city,
        zip=profile.zip,
        country_id=profile.country_id,
        photo_url=profile.photo_url,
        banner_photo_url=profile.banner_photo_url,
        name=profile.name,
        dob=profile.dob,
        followers_count=profile.get_followers_count(),
        following_count=profile.get_following_count(),
    )


def to_contributor_profile_entity(contributor: ContributorProfile) -> ContributorProfileEntity:
    return ContributorProfileEntity(
        user_id=contributor.user_id,
        preferred_location_ids=tuple(
            contributor.preferred_locations.values_list("id", flat=True)
        ),
        contribution_means_ids=tuple(
            contributor.contribution_means.values_list("id", flat=True)
        ),
    )


def to_auth_audit_event_entity(event: AuthAuditEvent) -> AuthAuditEventEntity:
    return AuthAuditEventEntity(
        id=event.id,
        user_id=event.user_id,
        email=event.email,
        event_code=event.event_code,
        success=event.success,
        ip_address=event.ip_address,
        user_agent=event.user_agent,
        metadata=event.metadata,
        created_at=event.created_at,
    )


def to_invited_user_entity(invited: InvitedUser) -> InvitedUserEntity:
    return InvitedUserEntity(
        id=invited.id,
        email=invited.email,
        invitation_code=invited.invitation_code,
        created_at=invited.created_at,
        updated_at=invited.updated_at,
    )
