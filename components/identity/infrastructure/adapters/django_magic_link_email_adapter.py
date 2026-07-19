"""Adapter that delivers the passwordless sign-in email via Django.

Symmetric to ``DjangoEmailVerificationAdapter`` — same backend
(``EmailMultiAlternatives`` + HTML+plaintext templates), different
subject + content. Wrapped in a thin class so the controller calls
``send_magic_link_email(...)`` and the use case stays framework-free.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class DjangoMagicLinkEmailAdapter:
    """Email delivery for the magic-link sign-in flow."""

    def send_magic_link_email(
        self,
        *,
        email: str,
        sign_in_url: str,
        site_name: str,
        site_domain: str,
        ttl_minutes: int,
    ) -> bool:
        from django.conf import settings as django_settings
        from django.core.mail import EmailMultiAlternatives
        from django.template.loader import render_to_string

        context = {
            "email": email,
            "site_name": site_name,
            "site_domain": site_domain,
            "sign_in_url": sign_in_url,
            "ttl_minutes": ttl_minutes,
        }
        try:
            html_body = render_to_string("email/magic_link.html", context)
        except Exception:
            logger.exception(
                "magic_link_email_template_missing: falling back to plain text"
            )
            html_body = None
        plaintext_body = render_to_string("email/magic_link.txt", context)

        default_from = getattr(
            django_settings, "DEFAULT_FROM_EMAIL", f"noreply@{site_domain}"
        )
        msg = EmailMultiAlternatives(
            subject=f"Sign in to {site_name}",
            body=plaintext_body,
            from_email=default_from,
            to=[email],
        )
        if html_body:
            msg.attach_alternative(html_body, "text/html")
        try:
            sent_count = msg.send(fail_silently=False)
        except Exception:
            logger.exception(
                "magic_link_email_send_failed email=%s", email
            )
            return False
        if not sent_count:
            logger.warning(
                "magic_link_email_send_failed email=%s sent_count=0", email
            )
            return False
        return True
