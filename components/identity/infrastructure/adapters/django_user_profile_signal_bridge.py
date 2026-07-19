"""Signal bridge: create/sync UserProfile on CustomUser save.

Extracted from apps/social/models.py — user profile lifecycle is an
identity-domain concern, not a social-domain concern.

Registration happens in apps/users/apps.py:ready().
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


class DjangoUserProfileSignalBridge:
    """Registers post_save on CustomUser to ensure a UserProfile always exists."""

    @staticmethod
    def register() -> None:
        from infrastructure.persistence.users.models import CustomUser

        post_save.connect(
            _handle_user_post_save,
            sender=CustomUser,
            weak=False,
            dispatch_uid="identity:user_profile_post_save",
        )


def _handle_user_post_save(sender, instance, created, **kwargs):
    """Create or sync the user profile after user save.

    On creation → create a new UserProfile, UserPreference, and Cart.
    On update  → save the existing profile (keeps one-to-one in sync).
    """
    from infrastructure.persistence.users.models import UserProfile

    if created:
        UserProfile.objects.get_or_create(user=instance)
        _bootstrap_user_defaults(instance)
        return

    try:
        instance.profile.save()
    except sender.profile.RelatedObjectDoesNotExist:
        # Profile missing for existing user — create it defensively.
        UserProfile.objects.get_or_create(user=instance)
    except Exception:
        logger.exception(
            "Failed to sync UserProfile for user %s",
            getattr(instance, "id", "unknown"),
        )


def _bootstrap_user_defaults(user):
    """Create default UserPreference for a new user.

    These used to be created by the frontend post-registration, but that
    fires before the user has a JWT token — causing 401s and error toasts.
    Creating them server-side on user creation is the correct place.
    """
    try:
        from infrastructure.persistence.notifications.userpreferences.models import UserPreference

        UserPreference.objects.get_or_create(user=user)
    except Exception:
        logger.exception("Failed to create UserPreference for user %s", user.id)
