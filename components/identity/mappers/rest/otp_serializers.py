"""Serializers for OTP endpoints."""

from rest_framework import serializers


class PasswordConfirmSerializer(serializers.Serializer):
    """Confirm the current password for sensitive 2FA actions."""

    password = serializers.CharField(write_only=True, trim_whitespace=False)
