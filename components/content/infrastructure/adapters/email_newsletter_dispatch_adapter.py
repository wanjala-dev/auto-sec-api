"""Email dispatch adapter for newsletters.

Implements ``NewsletterDispatchPort`` via Django's email backend. The
backend chosen at runtime (SMTP, SES, console for dev) is whatever
``EMAIL_BACKEND`` is set to in settings.

This rewrite (2026-06-11, part of the writing-surface paid-ready
hardening) replaces the previous BCC blast with one ``EmailMultiAlternatives``
per recipient. Why:

- Each subscriber needs their own ``List-Unsubscribe`` header pointing
  to their own tokenized URL (RFC 8058 one-click). Bulk BCC sends one
  header for the whole batch — they can't have per-recipient tokens.
- ``{{subscriber_first_name}}`` / ``{{unsubscribe_url}}`` substitution
  needs to happen per recipient, in both HTML and plain bodies.
- Per-recipient failures (one bad address) shouldn't block the rest of
  the batch; we log + count + continue. Whole-batch failures (SMTP
  unreachable, auth error) still raise.

Failure semantics:

- Whole-batch exception (SMTP/SES unreachable, signature error, etc.):
  raises immediately, no partial state. Caller rolls back the status
  transition — newsletters in SENT with no delivery is a silent
  integrity bug.
- Per-recipient exception (one address rejected): logged at WARNING,
  counted in ``DispatchSummary.failed``, loop continues. The use case
  publishes ``NewsletterSent`` with the delivered count, not the
  attempted count.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from html import escape

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection

from components.content.domain.value_objects.dispatch_summary import DispatchSummary
from components.content.domain.value_objects.subscriber_dispatch_target import (
    SubscriberDispatchTarget,
)
from components.shared_kernel.domain.errors import ValidationError

logger = logging.getLogger(__name__)


# ─────────────────── HTML → plain fallback ───────────────────


def _html_to_plain(html: str) -> str:
    """Crude HTML → plain-text fallback for multipart emails.

    Used only when the caller didn't pre-compute a plain body. Strips
    tags, decodes a handful of entities, normalises whitespace. Good
    enough for plain-text email clients to see readable copy; a
    production deployment could swap in ``html2text`` for fidelity.
    """

    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ─────────────────── per-recipient substitution ───────────────────


_TOKEN_FIRST_NAME = "{{subscriber_first_name}}"
_TOKEN_NAME = "{{subscriber_name}}"
_TOKEN_EMAIL = "{{subscriber_email}}"
_TOKEN_UNSUBSCRIBE_URL = "{{unsubscribe_url}}"


def _substitute_recipient_tokens(
    body: str,
    *,
    target: SubscriberDispatchTarget,
    unsubscribe_url: str,
    escape_html: bool,
) -> str:
    """Replace the four recipient-scoped tokens in ``body``.

    ``escape_html=True`` HTML-escapes the substituted values so a
    subscriber whose name contains ``<script>`` doesn't inject markup
    into the rendered email. Plain bodies skip escaping.
    """

    def maybe_escape(value: str) -> str:
        return escape(value, quote=True) if escape_html else value

    return (
        body.replace(_TOKEN_FIRST_NAME, maybe_escape(target.first_name()))
        .replace(_TOKEN_NAME, maybe_escape(target.name))
        .replace(_TOKEN_EMAIL, maybe_escape(target.email))
        .replace(_TOKEN_UNSUBSCRIBE_URL, maybe_escape(unsubscribe_url))
    )


# ─────────────────── unsubscribe footer injection ───────────────────


_HTML_FOOTER_MARKER = "<!-- content:unsubscribe-footer -->"


def _append_unsubscribe_footer_html(html: str, unsubscribe_url: str) -> str:
    """Append a small footer with the unsubscribe link if the body
    doesn't already contain the token.

    The marker comment lets the editor opt out by including its own
    footer + the comment. The body is wrapped in a ``<div>`` styled to
    look unobtrusive — small grey text. Inlined CSS because email
    clients drop ``<style>`` blocks.
    """

    if _TOKEN_UNSUBSCRIBE_URL in html or _HTML_FOOTER_MARKER in html:
        return html

    footer = (
        f"{_HTML_FOOTER_MARKER}"
        '<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e5e5e5;'
        'font-size:12px;color:#666;font-family:Arial,sans-serif;">'
        f"You are receiving this because you subscribed. "
        f'<a href="{escape(unsubscribe_url, quote=True)}" '
        f'style="color:#666;text-decoration:underline;">Unsubscribe</a>'
        "</div>"
    )
    return html + footer


_PLAIN_FOOTER_MARKER = "-- unsubscribe --"


def _append_unsubscribe_footer_plain(plain: str, unsubscribe_url: str) -> str:
    if _TOKEN_UNSUBSCRIBE_URL in plain or _PLAIN_FOOTER_MARKER in plain:
        return plain
    return (
        f"{plain}\n\n"
        f"{_PLAIN_FOOTER_MARKER}\n"
        f"You are receiving this because you subscribed.\n"
        f"Unsubscribe: {unsubscribe_url}\n"
    )


# ─────────────────── open-tracking pixel (task #25) ───────────────────


def _append_open_pixel(html: str, token: str) -> str:
    """Embed the recipient's open-tracking pixel — a 1×1 image served by
    the public open endpoint, keyed by their dispatch record's token.
    Absolute URL via the Sites framework (the Site domain IS the API
    host in prod)."""
    from components.shared_platform.infrastructure.services.core_utils import (
        build_absolute_media_url,
    )

    pixel_url = build_absolute_media_url(f"/api/v1/content/t/o/{token}/")
    return (
        html + f'<img src="{escape(pixel_url, quote=True)}" width="1" height="1" '
        'alt="" style="display:block;border:0;" />'
    )


# ─────────────────── adapter ───────────────────


class EmailNewsletterDispatchAdapter:
    def send(
        self,
        *,
        subject: str,
        html_body: str,
        plain_body: str,
        targets: Sequence[SubscriberDispatchTarget],
        sender_address: str | None = None,
        sender_name: str | None = None,
        reply_to: str | None = None,
        list_unsubscribe_base_url: str,
        list_unsubscribe_mailto: str | None = None,
        open_tokens: dict[str, str] | None = None,
    ) -> DispatchSummary:
        if not targets:
            raise ValidationError("targets must not be empty")
        if not list_unsubscribe_base_url:
            raise ValidationError("list_unsubscribe_base_url is required")

        from_address = (
            sender_address
            or getattr(settings, "EMAIL_FROM", None)
            or getattr(settings, "DEFAULT_FROM_EMAIL", "info@octopusintl.org")
        )
        # If sender_name set, format as "Display Name <addr@octopusintl.org>".
        # The Workspace name templating happens at the use case layer; the
        # adapter just stitches together what it's given.
        if sender_name:
            from_field = f"{sender_name} <{from_address}>"
        else:
            from_field = from_address

        # Compute plain fallback once if the caller didn't pass one.
        if not plain_body:
            plain_body = _html_to_plain(html_body)

        # Open a single connection for the whole batch — Django's email
        # backend will reuse it across messages, far cheaper than
        # connect-per-message for SMTP/SES.
        connection = get_connection()
        connection.open()
        delivered = 0
        failed = 0
        delivered_emails: list[str] = []
        failed_emails: list[str] = []
        try:
            for target in targets:
                unsubscribe_url = list_unsubscribe_base_url.rstrip("/") + "/" + str(target.unsubscribe_token)
                # Substitute tokens per recipient — HTML escapes values,
                # plain text doesn't.
                html_personalized = _substitute_recipient_tokens(
                    html_body,
                    target=target,
                    unsubscribe_url=unsubscribe_url,
                    escape_html=True,
                )
                plain_personalized = _substitute_recipient_tokens(
                    plain_body,
                    target=target,
                    unsubscribe_url=unsubscribe_url,
                    escape_html=False,
                )
                # Defensive footer: appended only when the body didn't
                # already include the unsubscribe token.
                html_personalized = _append_unsubscribe_footer_html(html_personalized, unsubscribe_url)
                plain_personalized = _append_unsubscribe_footer_plain(plain_personalized, unsubscribe_url)

                # Open-tracking pixel (task #25) — one per recipient,
                # keyed by their dispatch record's token. HTML copy
                # only; the plain fallback stays clean.
                open_token = (open_tokens or {}).get(target.email)
                if open_token:
                    html_personalized = _append_open_pixel(html_personalized, open_token)

                # RFC 8058 List-Unsubscribe header. Two slots — URL +
                # mailto (if configured). The Post header tells the
                # inbox provider this URL handles one-click POSTs.
                if list_unsubscribe_mailto:
                    list_unsubscribe = (
                        f"<{unsubscribe_url}>, "
                        f"<mailto:{list_unsubscribe_mailto}?subject=unsubscribe%20{target.unsubscribe_token}>"
                    )
                else:
                    list_unsubscribe = f"<{unsubscribe_url}>"

                headers = {
                    "List-Unsubscribe": list_unsubscribe,
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                }

                message = EmailMultiAlternatives(
                    subject=subject,
                    body=plain_personalized,
                    from_email=from_field,
                    to=[target.email],
                    reply_to=[reply_to] if reply_to else None,
                    headers=headers,
                    connection=connection,
                )
                message.attach_alternative(html_personalized, "text/html")
                try:
                    message.send(fail_silently=False)
                    delivered += 1
                    delivered_emails.append(target.email)
                except Exception:
                    # Per-recipient failure: log + count + continue.
                    # Don't bubble — a single bad address shouldn't kill
                    # the batch. The summary captures it.
                    logger.exception(
                        "newsletter_recipient_send_failed token=%s",
                        target.unsubscribe_token,
                    )
                    failed += 1
                    failed_emails.append(target.email)
        finally:
            connection.close()

        logger.info(
            "newsletter_dispatch_summary delivered=%d failed=%d total=%d subject=%r",
            delivered,
            failed,
            len(targets),
            subject,
        )
        return DispatchSummary(
            delivered=delivered,
            failed=failed,
            delivered_emails=tuple(delivered_emails),
            failed_emails=tuple(failed_emails),
        )
