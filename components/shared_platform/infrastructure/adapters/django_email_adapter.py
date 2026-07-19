"""Django adapter implementing EmailSendingPort.

Delegates to Django's EmailMultiAlternatives so the application layer
never imports django.core.mail directly.
"""

from __future__ import annotations

import logging

from components.shared_platform.application.ports.email_sending_port import (
    EmailMessage,
    EmailSendingPort,
)

logger = logging.getLogger(__name__)


class DjangoEmailAdapter(EmailSendingPort):
    """Concrete adapter backed by Django email backend."""

    def send(self, message: EmailMessage) -> bool:
        from django.conf import settings
        from django.core.mail import EmailMultiAlternatives

        from_email = message.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "")

        msg = EmailMultiAlternatives(
            subject=message.subject,
            body=message.text_body,
            from_email=from_email,
            to=message.to,
            cc=message.cc or None,
            bcc=message.bcc or None,
            reply_to=message.reply_to or None,
        )

        if message.html_body:
            msg.attach_alternative(message.html_body, "text/html")

        for filename, content, mimetype in message.attachments:
            msg.attach(filename, content, mimetype)

        sent = msg.send(fail_silently=True)
        if not sent:
            logger.warning("Email send failed: subject=%r, to=%s", message.subject, message.to)
            return False
        return True

    def send_templated(
        self,
        *,
        to,
        subject,
        template,
        context,
        from_email="",
        workspace_id=None,
    ) -> bool:
        from django.conf import settings
        from django.template.loader import render_to_string
        from django.utils.html import strip_tags

        if workspace_id:
            from components.shared_platform.infrastructure.services.pdf_brand_assets import (
                resolve_brand_colors,
            )

            _brand = resolve_brand_colors(workspace_id)
            # Spread caller ``context`` LAST so an explicit caller-provided
            # brand_primary still wins over the resolved workspace brand.
            context = {
                "brand_primary": _brand["primary_light"],
                "brand_secondary": _brand["secondary"],
                **context,
            }

        html_body = render_to_string(template, context)
        text_body = strip_tags(html_body)
        resolved_from = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "")

        return self.send(
            EmailMessage(
                subject=subject,
                to=list(to),
                text_body=text_body,
                html_body=html_body,
                from_email=resolved_from,
            )
        )
