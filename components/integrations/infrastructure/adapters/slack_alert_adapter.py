"""Outbound Slack delivery for SinkConnector(kind=slack) — the alert sink adapter.

Reads the workspace's enabled Slack sinks, decrypts each bot token via the shared
secret envelope, and POSTs to Slack ``chat.postMessage`` (plain ``requests``, as the
GitHub/IOC adapters do). Delivery result is stamped on the row (``last_delivery_at`` /
``last_error``) so the connector's health is visible. Never raises on an expected
delivery failure — one dead sink must not break the finding pipeline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

import requests
from django.views.decorators.debug import sensitive_variables

from components.integrations.application.ports.alert_sink_port import (
    AlertMessage,
    AlertSinkPort,
    SlackSink,
)
from components.integrations.application.providers.secret_envelope_provider import (
    decrypt_secret,
    get_secret_decryption_error,
)
from components.integrations.domain.alert_policy import DEFAULT_MIN_SEVERITY

logger = logging.getLogger(__name__)

_SLACK_POST_MESSAGE_URL = "https://slack.com/api/chat.postMessage"
_TIMEOUT_SECONDS = 10


class SlackAlertAdapter(AlertSinkPort):
    def enabled_slack_sinks(self, workspace_id: UUID) -> list[SlackSink]:
        from infrastructure.persistence.integrations.models import SinkConnector

        sinks: list[SlackSink] = []
        rows = SinkConnector.objects.filter(workspace_id=workspace_id, kind=SinkConnector.Kind.SLACK, is_enabled=True)
        for row in rows.iterator(chunk_size=100):
            try:
                token = decrypt_secret(row.secret_ciphertext)
            except get_secret_decryption_error():
                logger.exception("slack_sink_token_decrypt_failed sink_id=%s", row.id)
                continue
            if not token:
                logger.warning("slack_sink_missing_token sink_id=%s", row.id)
                continue
            config = row.config or {}
            sinks.append(
                SlackSink(
                    id=row.id,
                    channel=str(config.get("channel") or ""),
                    min_severity=str(config.get("min_severity") or DEFAULT_MIN_SEVERITY),
                    token=token,
                )
            )
        return sinks

    @sensitive_variables()  # keep the bot token out of any error-page/traceback capture
    def deliver(self, sink: SlackSink, message: AlertMessage) -> bool:
        payload: dict = {"text": self._render(message)}
        if sink.channel:
            payload["channel"] = sink.channel
        try:
            resp = requests.post(
                _SLACK_POST_MESSAGE_URL,
                headers={"Authorization": f"Bearer {sink.token}"},
                json=payload,
                timeout=_TIMEOUT_SECONDS,
            )
            body = resp.json() if resp.content else {}
            ok = bool(body.get("ok"))
            error = None if ok else str(body.get("error") or f"http_{resp.status_code}")
        except (requests.RequestException, ValueError) as exc:
            logger.exception("slack_delivery_failed sink_id=%s", sink.id)
            ok, error = False, str(exc)

        self._stamp(sink.id, ok=ok, error=error)
        if ok:
            logger.info("slack_delivery_ok sink_id=%s severity=%s", sink.id, message.severity)
        else:
            logger.warning("slack_delivery_error sink_id=%s error=%s", sink.id, error)
        return ok

    @staticmethod
    def _render(message: AlertMessage) -> str:
        lines = [f"*{message.title}*", "", message.text]
        if message.context_url:
            lines.append(f"<{message.context_url}|View in Auto-Sec>")
        return "\n".join(lines)

    @staticmethod
    def _stamp(sink_id: UUID, *, ok: bool, error: str | None) -> None:
        from infrastructure.persistence.integrations.models import SinkConnector

        if ok:
            SinkConnector.objects.filter(id=sink_id).update(last_delivery_at=datetime.now(UTC), last_error="")
        else:
            SinkConnector.objects.filter(id=sink_id).update(last_error=(error or "")[:2000])
