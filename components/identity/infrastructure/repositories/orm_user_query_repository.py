"""ORM adapter implementing UserQueryPort.

This adapter provides raw ORM model queries for controller and serialization logic.
It returns ORM models directly rather than domain entities.
"""

from __future__ import annotations

from components.identity.application.ports.user_query_port import UserQueryPort


class OrmUserQueryRepository(UserQueryPort):
    """Concrete adapter backed by Django ORM for query operations."""

    def get_by_id(self, user_id, with_profile: bool = False):
        """Get user by ID, optionally with profile pre-fetched."""
        from infrastructure.persistence.users.models import CustomUser

        qs = CustomUser.objects.all()
        if with_profile:
            qs = qs.select_related("profile", "contributor_profile")
        try:
            return qs.get(id=user_id)
        except CustomUser.DoesNotExist:
            return None

    def get_by_email(self, email: str):
        """Get user by email."""
        from infrastructure.persistence.users.models import CustomUser

        try:
            return CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            return None

    def find_by_email_and_username(self, email: str, username: str):
        """Find users matching email and username."""
        from infrastructure.persistence.users.models import CustomUser

        return CustomUser.objects.filter(email=email, username=username)

    def get_queryset(self):
        """Return the base user queryset with profile pre-fetched."""
        from infrastructure.persistence.users.models import CustomUser

        return CustomUser.objects.select_related("profile", "contributor_profile")

    def get_profile(self, user_id):
        """Get user profile by user ID."""
        from infrastructure.persistence.users.models import UserProfile

        try:
            return UserProfile.objects.get(user_id=user_id)
        except UserProfile.DoesNotExist:
            return None

    def list_pending_invitations(self, email: str):
        """List pending invitations for an email."""
        from infrastructure.persistence.team.models import Invitation

        return Invitation.objects.filter(
            email=email, status=Invitation.INVITED
        ).order_by('-id')

    def get_system_actor(self):
        """Get system actor (superuser or staff) for audit events."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        return (
            User.objects.filter(is_superuser=True).first()
            or User.objects.filter(is_staff=True).first()
        )
