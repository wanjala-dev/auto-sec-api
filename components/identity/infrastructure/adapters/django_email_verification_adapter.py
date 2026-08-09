"""Infrastructure adapter implementing EmailVerificationPort.

Delegates to Django's EmailMultiAlternatives for sending HTML/text
verification emails. FAIL-LOUD: a backend send failure raises (after a
``logger.exception`` with ids only — never the token or the address) so
the Celery caller retries instead of the API claiming success while
delivering nothing. This adapter is invoked from the background worker
(``identity.send_verification_email``), never inline in a request.
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
        try:
            sent_count = msg.send(fail_silently=False)
        except Exception:
            # No token / no address in the log line — user_id is enough to
            # trace, and the traceback carries the SMTP root cause.
            logger.exception("verification_email_send_failed user_id=%s", user_id)
            raise
        if not sent_count:
            logger.error("verification_email_send_reported_zero user_id=%s", user_id)
            raise RuntimeError("email backend accepted no messages for verification email")
        logger.info("verification_email_sent user_id=%s", user_id)
        return True
