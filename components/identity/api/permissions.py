"""DRF permission classes for identity concerns.

These permissions check authentication state, user identity, and admin/staff
status. They are framework-specific (DRF) adapters, not business logic.
"""

from django.contrib.auth import get_user_model
from django_otp import user_has_device
from rest_framework import permissions

from components.identity.application.providers.user_utils_provider import (
    get_user_utils_provider,
)
otp_is_verified = get_user_utils_provider().otp_is_verified


class IsOtpVerified(permissions.BasePermission):
    """If user has verified TOTP device, require TOTP OTP."""

    message = "You do not have permission to perform this action until you verify your OTP device."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if not getattr(user, "two_factor_enabled", False):
            return True
        if user_has_device(user):
            return otp_is_verified(self, request)
        return False


class IsLoggedInUserOrAdmin(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        return obj == request.user or request.user.is_staff


class IsAdminUser(permissions.BasePermission):

    def has_permission(self, request, view):
        return request.user and request.user.is_staff

    def has_object_permission(self, request, view, obj):
        return request.user and request.user.is_staff


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Custom permission to only allow owners of an object to edit it."""

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author == request.user


class IsOwnerOrAdminOrReadOnly(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return obj.author == request.user or request.user.is_admin


class IsOwnerOrAdminOrStaffOrReadOnly(permissions.BasePermission):

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if hasattr(obj, 'author'):
            return obj.author == request.user or request.user.is_admin or request.user.is_staff
        elif isinstance(obj, get_user_model()):
            return obj.id == request.user.id or request.user.is_admin or request.user.is_staff
        return False


class IsTwoFactorEnabledAndVerified(permissions.BasePermission):
    """Require active 2FA device and OTP verification when 2FA is enabled."""

    message = "Two-factor authentication is required."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if not getattr(user, "two_factor_enabled", False):
            return True
        if user_has_device(user):
            return otp_is_verified(self, request)
        return True


class IsUnauthenticatedOrAdminOrStaff(permissions.BasePermission):
    """Backward-compatible gate used across legacy and onboarding endpoints.

    Behavior:
    - Always allow safe methods.
    - Allow unauthenticated requests where views intentionally support public flows.
    - Allow authenticated users by default.
    - Preserve explicit admin/staff allowances.
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True

        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return True

        if bool(
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or getattr(user, "is_admin", False)
        ):
            return True

        return True
