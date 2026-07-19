"""Notify + email recipients of a Share-in-chat card (task #21).

Reuses the canonical plumbing (DRY hard rule): the ``NotificationDispatcher``
funnel for the in-app bell and the shared ``EmailSendingPort`` for the email —
never hand-rolled send paths. Everything is failure-safe: sharing is
decoration on the message send.
"""

from __future__ import annotations

import html as html_lib
import logging
from collections.abc import Sequence
from uuid import UUID

logger = logging.getLogger(__name__)


class ShareNotificationAdapter:
    def notify_share(
        self,
        *,
        sender_id: UUID,
        recipient_user_ids: Sequence[UUID],
        share: dict,
        workspace_id: UUID | None = None,
    ) -> None:
        try:
            from django.contrib.auth import get_user_model

            from components.notifications.infrastructure.adapters.notification_service import (
                NotificationDispatcher,
            )
            from components.shared_platform.application.ports.email_sending_port import (
                EmailMessage,
            )
            from components.shared_platform.application.providers.email_adapter_provider import (
                get_email_adapter_provider,
            )
            from components.shared_platform.infrastructure.services.core_utils import (
                resolve_frontend_base_url,
            )

            User = get_user_model()
            sender = User.objects.filter(pk=sender_id).first()
            if sender is None:
                return
            sender_name = f"{sender.first_name} {sender.last_name}".strip() or sender.username or "A teammate"
            title = str(share.get("title") or "something")
            url = str(share.get("url") or "")
            excerpt = str(share.get("excerpt") or "")
            base_url = resolve_frontend_base_url()
            absolute_url = url if url.startswith("http") else f"{base_url.rstrip('/')}{url}"

            recipients = list(User.objects.filter(pk__in=list(recipient_user_ids)))

            # In-app leg goes through the canonical dispatcher funnel once for
            # the whole recipient set (preference filtering + async fan-out).
            try:
                NotificationDispatcher().dispatch(
                    actor=sender,
                    workspace=None,
                    verb=f"shared “{title}” with you",
                    notification_type="share",
                    recipients=recipients,
                    metadata={"share": share},
                )
            except Exception:
                logger.exception("share_notify.notification_failed sender=%s", sender_id)

            email_adapter = get_email_adapter_provider().adapter()
            for recipient in recipients:
                recipient_id = recipient.pk
                if recipient.email:
                    try:
                        excerpt_html = (
                            f'<p style="margin:12px 0 0;color:#4b5563;">{html_lib.escape(excerpt)}</p>'
                            if excerpt
                            else ""
                        )
                        email_adapter.send(
                            EmailMessage(
                                subject=f"{sender_name} shared “{title}” with you",
                                to=[recipient.email],
                                html_body=(
                                    '<div style="font-family:Arial,sans-serif;color:#1f2937;'
                                    'line-height:1.6;max-width:560px;">'
                                    f"<p>{html_lib.escape(sender_name)} shared "
                                    f"<strong>“{html_lib.escape(title)}”</strong> with you in Messages.</p>"
                                    f"{excerpt_html}"
                                    f'<p style="margin:16px 0 0;"><a href="{html_lib.escape(absolute_url)}" '
                                    'style="color:#047857;font-weight:600;">Open it →</a></p>'
                                    "</div>"
                                ),
                                text_body=f"{sender_name} shared “{title}” with you: {absolute_url}",
                            )
                        )
                    except Exception:
                        logger.exception(
                            "share_notify.email_failed recipient=%s sender=%s",
                            recipient_id,
                            sender_id,
                        )
        except Exception:
            logger.exception("share_notify.failed sender=%s", sender_id)
