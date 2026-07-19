"""ORM adapter implementing UserRepositoryPort.

This is the infrastructure boundary — Django ORM lives here, not in domain/application.
"""

from __future__ import annotations

from uuid import UUID

from infrastructure.persistence.users.models import CustomUser, UserProfile
from components.identity.domain.entities.user_entity import UserEntity
from components.identity.domain.entities.user_profile_entity import UserProfileEntity
from components.identity.mappers.db.user_mapper import to_user_entity, to_user_profile_entity
from components.identity.application.ports.user_repository_port import UserRepositoryPort


class OrmUserRepository(UserRepositoryPort):
    """Concrete adapter backed by Django ORM."""

    def find_by_id(self, user_id: UUID) -> UserEntity | None:
        try:
            user = CustomUser.objects.get(id=user_id)
            return to_user_entity(user)
        except CustomUser.DoesNotExist:
            return None

    def find_by_email(self, email: str) -> UserEntity | None:
        try:
            user = CustomUser.objects.get(email=email.strip().lower())
            return to_user_entity(user)
        except CustomUser.DoesNotExist:
            return None

    def find_profile(self, user_id: UUID) -> UserProfileEntity | None:
        try:
            profile = UserProfile.objects.select_related("user").get(user_id=user_id)
            return to_user_profile_entity(profile)
        except UserProfile.DoesNotExist:
            return None

    def create_user(self, username: str, email: str, password: str) -> UserEntity:
        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            password=password,
        )
        return to_user_entity(user)

    def verify_email(self, user_id: UUID) -> None:
        CustomUser.objects.filter(id=user_id).update(is_verified=True)

    def set_password(self, user_id: UUID, new_password: str) -> None:
        user = CustomUser.objects.get(id=user_id)
        user.set_password(new_password)
        user.save(update_fields=["password"])

    def check_password(self, user_id: UUID, password: str) -> bool:
        try:
            user = CustomUser.objects.get(id=user_id)
            return user.check_password(password)
        except CustomUser.DoesNotExist:
            return False

    def validate_new_password(self, user_id: UUID, password: str) -> list[str]:
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        try:
            user = CustomUser.objects.get(id=user_id)
        except CustomUser.DoesNotExist:
            return ["User not found."]
        try:
            validate_password(password, user=user)
            return []
        except ValidationError as exc:
            return list(exc.messages)

    def enable_two_factor(self, user_id: UUID) -> None:
        from django.utils import timezone

        CustomUser.objects.filter(id=user_id).update(
            two_factor_enabled=True,
            two_factor_confirmed_at=timezone.now(),
        )

    def disable_two_factor(self, user_id: UUID) -> None:
        CustomUser.objects.filter(id=user_id).update(
            two_factor_enabled=False,
            two_factor_confirmed_at=None,
        )

    def get_workspace(self, workspace_id: UUID) -> dict | None:
        """Fetch workspace details by ID.

        Returns a dict with workspace info or None if not found.
        Uses lazy import to avoid circular dependency.
        """
        from infrastructure.persistence.workspaces.models import Workspace

        try:
            workspace = Workspace.objects.get(id=workspace_id)
            return {
                'id': str(workspace.id),
                'workspace_name': workspace.workspace_name,
                'icon': workspace.photo_url,
            }
        except Workspace.DoesNotExist:
            return None

    def ensure_workspace_follower(self, workspace_id: UUID, user_id: UUID) -> None:
        """Ensure user follows the given workspace.

        Delegates to the workspace facade to avoid coupling.
        Uses lazy imports to avoid circular dependencies.
        """
        from infrastructure.persistence.workspaces.models import Workspace
        from components.workspace.application.facades.workspace_facade import ensure_workspace_follower

        try:
            workspace = Workspace.objects.get(id=workspace_id)
            user = CustomUser.objects.get(id=user_id)
            ensure_workspace_follower(workspace, user)
        except (Workspace.DoesNotExist, CustomUser.DoesNotExist):
            pass
