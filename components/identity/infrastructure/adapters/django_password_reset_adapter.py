"""Infrastructure adapter implementing PasswordResetPort.

Wraps Django's password reset token generation, email sending,
and token validation behind the port contract.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.password_reset_port import (
    PasswordResetPort,
    PasswordResetTokenInfo,
)


class DjangoPasswordResetAdapter(PasswordResetPort):
    """Concrete adapter backed by Django auth utilities."""

    def generate_reset_token(self, user_id: UUID) -> PasswordResetTokenInfo:
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.utils.encoding import smart_bytes
        from django.utils.http import urlsafe_base64_encode

        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.get(id=user_id)
        uidb64 = urlsafe_base64_encode(smart_bytes(user.id))
        token = PasswordResetTokenGenerator().make_token(user)
        return PasswordResetTokenInfo(uidb64=uidb64, token=token)

    def send_reset_email(
        self,
        *,
        email: str,
        reset_url: str,
    ) -> bool:
        from components.identity.infrastructure.adapters.user_utils import Util

        email_body = (
            "Hello, \n Use link below to reset your password  \n" + reset_url
        )
        data = {
            "email_body": email_body,
            "to_email": email,
            "email_subject": "Reset your password",
        }
        Util.send_email(data)
        return True

    def validate_reset_token(self, uidb64: str, token: str) -> UUID | None:
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.utils.encoding import smart_str
        from django.utils.http import urlsafe_base64_decode

        from infrastructure.persistence.users.models import CustomUser

        try:
            user_id = smart_str(urlsafe_base64_decode(uidb64))
            user = CustomUser.objects.get(id=user_id)
            if not PasswordResetTokenGenerator().check_token(user, token):
                return None
            return UUID(str(user.id))
        except Exception:
            return None

    def set_new_password(self, user_id: UUID, password: str) -> None:
        from infrastructure.persistence.users.models import CustomUser

        user = CustomUser.objects.get(id=user_id)
        user.set_password(password)
        user.save(update_fields=["password"])
