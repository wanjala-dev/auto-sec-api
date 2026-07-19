"""Infrastructure adapter implementing EmailVerificationPort.

Delegates to Django's EmailMultiAlternatives for sending HTML/text
verification emails.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.identity.application.ports.email_verification_port import EmailVerificationPort

logger = logging.getLogger(__name__)


class DjangoEmailVerificationAdapter(EmailVerificationPort):
    """Concrete adapter backed by Django email backend."""

    def send_verification_email(
        self,
        *,
        user_id: UUID,
        email: str,
        username: str,
        verification_url: str,
        site_name: str,
        site_domain: str,
    ) -> bool:
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string

        context = {
            "name": username,
            "email": email,
            "site_name": site_name,
            "site_domain": site_domain,
            "redirect_link": verification_url,
        }

        contact_html_message = render_to_string("email/confirm_account.html", context)
        contact_plaintext_message = render_to_string("email/email-confirm.txt", context)

        from django.conf import settings as django_settings
        default_from = getattr(django_settings, "DEFAULT_FROM_EMAIL", f"noreply@{site_domain}")

        msg = EmailMultiAlternatives(
            subject=f"Welcome to {site_name}",
            body=contact_plaintext_message,
            from_email=default_from,
            to=[email],
        )
        msg.attach_alternative(contact_html_message, "text/html")
        sent_count = msg.send(fail_silently=True)
        if not sent_count:
            logger.warning(
                "Register email send failed for user_id=%s; continuing without blocking signup",
                user_id,
            )
            return False
        return True
