"""Slack delivery adapter — the first :class:`DeliveryChannelPort` (ADR 0016 D3).

Two auth modes, both first-class:

* ``webhook_url`` — the customer creates an incoming webhook in their own Slack,
  picks the channel at authorization time, and pastes one URL. No OAuth consent,
  no app registration on our side. The URL **is** the credential, so it is stored
  in the Fernet envelope and never echoed. Host is allowlisted to
  ``hooks.slack.com/services/`` — the strongest SSRF posture (a known destination
  set), which is why this kind needs no generic URL guard.
* ``bot_token`` — ``chat.postMessage`` with a bearer token, able to post to any
  channel the bot has joined. Pre-dates the webhook mode and stays supported.

Slack answers 429 with a ``Retry-After`` header; that instruction is surfaced on
:class:`DeliveryResult` so the sender task can honour it rather than guessing.
Redirects are disabled — a redirect off an allowlisted host is a failure, not a
hop to follow.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests
from django.views.decorators.debug import sensitive_variables

from components.integrations.application.ports.delivery_channel_port import (
    DeliveryChannelPort,
    DeliveryHealth,
    DeliveryMessage,
    DeliveryResult,
    ResolvedDeliveryConnection,
)

logger = logging.getLogger(__name__)

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
_SLACK_AUTH_TEST_URL = "https://slack.com/api/auth.test"
_WEBHOOK_HOST = "hooks.slack.com"
_WEBHOOK_PATH_PREFIX = "/services/"
_TIMEOUT_SECONDS = 10

# Slack errors that will never succeed on retry — the credential or destination
# is gone. Anything else (transport blip, 5xx, rate limit) is transient.
_PERMANENT_ERRORS = frozenset(
    {
        "invalid_auth",
        "account_inactive",
        "token_revoked",
        "no_service",
        "channel_not_found",
        "not_in_channel",
        "invalid_token",
    }
)

_VERIFY_TITLE = "Auto-Sec connected"
_VERIFY_BODY = "This channel will receive Auto-Sec alerts."


def is_slack_webhook_url(url: str) -> bool:
    """True when ``url`` is a Slack incoming-webhook URL.

    Strict allowlist (ADR 0016 D6): https, exact host, ``/services/`` path prefix.
    Anything else is rejected before a request is ever made, which is what lets
    this kind skip the generic SSRF guard.
    """
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == _WEBHOOK_HOST
        and parsed.path.startswith(_WEBHOOK_PATH_PREFIX)
        and len(parsed.path) > len(_WEBHOOK_PATH_PREFIX)
    )


class SlackDeliveryAdapter(DeliveryChannelPort):
    """Posts to Slack via an incoming webhook or ``chat.postMessage``."""

    KIND = "slack"

    # ── DeliveryChannelPort ────────────────────────────────────────────────

    def verify(self, connection: ResolvedDeliveryConnection) -> DeliveryHealth:
        probe = DeliveryMessage(title=_VERIFY_TITLE, body=_VERIFY_BODY, severity="informational")
        if connection.auth_mode == "bot_token":
            # auth.test is genuinely side-effect free — prefer it over a test post.
            result = self._post(
                _SLACK_AUTH_TEST_URL,
                headers={"Authorization": f"Bearer {connection.secret}"},
                payload={},
                connection_id=connection.id,
            )
            return DeliveryHealth(ok=result.ok, detail=result.detail)
        # An incoming webhook has no probe endpoint — a real test message IS the probe.
        result = self.deliver(connection, probe)
        return DeliveryHealth(ok=result.ok, detail=result.detail)

    def deliver(self, connection: ResolvedDeliveryConnection, message: DeliveryMessage) -> DeliveryResult:
        if connection.auth_mode == "bot_token":
            payload = {"text": self._render_text(message), "blocks": self._render_blocks(message)}
            if connection.channel:
                payload["channel"] = connection.channel
            return self._post(
                _SLACK_POST_MESSAGE_URL,
                headers={"Authorization": f"Bearer {connection.secret}"},
                payload=payload,
                connection_id=connection.id,
            )

        if not is_slack_webhook_url(connection.secret):
            # Refuse to make the request at all rather than trusting a stored value.
            logger.warning("slack_delivery_rejected_url connection_id=%s", connection.id)
            return DeliveryResult(
                ok=False,
                detail="Stored webhook URL is not a valid https://hooks.slack.com/services/ URL.",
                permanent=True,
            )
        payload = {"text": self._render_text(message), "blocks": self._render_blocks(message)}
        return self._post(connection.secret, headers={}, payload=payload, connection_id=connection.id)

    # ── HTTP ───────────────────────────────────────────────────────────────

    @sensitive_variables()
    def _post(self, url: str, *, headers: dict, payload: dict, connection_id) -> DeliveryResult:
        """One POST, translated into a DeliveryResult. Never raises for an expected failure."""
        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            logger.exception("slack_delivery_transport_error connection_id=%s", connection_id)
            return DeliveryResult(ok=False, detail=f"transport error: {exc}"[:500])

        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))

        if resp.status_code == 429:
            logger.warning(
                "slack_delivery_rate_limited connection_id=%s retry_after=%s", connection_id, retry_after
            )
            return DeliveryResult(ok=False, detail="rate limited by Slack", retry_after_seconds=retry_after or 60)

        # The webhook endpoint answers "ok" as plain text; the Web API answers JSON
        # with {"ok": bool, "error": str} — and does so under HTTP 200, so the body
        # is authoritative wherever it parses.
        error = _slack_error(resp)
        if error is None:
            logger.info("slack_delivery_ok connection_id=%s", connection_id)
            return DeliveryResult(ok=True)

        permanent = error in _PERMANENT_ERRORS or 400 <= resp.status_code < 500
        logger.warning(
            "slack_delivery_error connection_id=%s error=%s status=%s permanent=%s",
            connection_id,
            error,
            resp.status_code,
            permanent,
        )
        return DeliveryResult(
            ok=False, detail=error[:500], retry_after_seconds=retry_after, permanent=permanent
        )

    # ── Rendering ──────────────────────────────────────────────────────────

    @staticmethod
    def _render_text(message: DeliveryMessage) -> str:
        """Plain-text fallback — what notifications and unfurls show."""
        lines = [message.title]
        if message.body:
            lines.append(message.body)
        if message.link:
            lines.append(message.link)
        return "\n".join(lines)

    @staticmethod
    def _render_blocks(message: DeliveryMessage) -> list[dict]:
        """Block Kit rendering. Section text caps at 3000 chars — truncate, never 400."""
        blocks: list[dict] = [
            {"type": "header", "text": {"type": "plain_text", "text": message.title[:150], "emoji": True}}
        ]
        if message.body:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": message.body[:3000]}})
        if message.fields:
            rendered = [
                {"type": "mrkdwn", "text": f"*{label}*\n{value}"[:2000]}
                for label, value in list(message.fields.items())[:10]
            ]
            blocks.append({"type": "section", "fields": rendered})
        if message.link:
            blocks.append(
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "View in Auto-Sec", "emoji": True},
                            "url": message.link,
                        }
                    ],
                }
            )
        return blocks


def _slack_error(resp) -> str | None:
    """Return Slack's error string, or None when the call succeeded."""
    try:
        body = resp.json() if resp.content else {}
    except ValueError:
        body = {}
    if isinstance(body, dict) and "ok" in body:
        return None if body.get("ok") else str(body.get("error") or f"http_{resp.status_code}")
    # Incoming webhooks reply with the literal body "ok" and no JSON.
    if resp.status_code == 200:
        return None
    return f"http_{resp.status_code}"


def _parse_retry_after(value: str | None) -> int | None:
    """Slack sends Retry-After as whole seconds. Ignore anything unparseable."""
    if not value:
        return None
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None
