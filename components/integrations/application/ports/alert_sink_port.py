"""Port: deliver an alert to a workspace's outbound sinks (Slack today).

Shaped to the core's need — "give me the workspace's enabled Slack sinks" and
"deliver this message to one" — not to Slack's API. The adapter reads the
``SinkConnector`` rows, decrypts the bot token, POSTs to Slack, and stamps the
delivery result; the application core only speaks in ``SlackSink`` + ``AlertMessage``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class SlackSink:
    """A resolved, ready-to-use Slack destination (token already decrypted)."""

    id: UUID
    channel: str
    min_severity: str
    token: str


@dataclass(frozen=True)
class AlertMessage:
    """A channel-agnostic alert — the adapter renders it for the target."""

    title: str
    text: str
    severity: str
    context_url: str = ""
    fields: dict = field(default_factory=dict)


class AlertSinkPort(ABC):
    @abstractmethod
    def enabled_slack_sinks(self, workspace_id: UUID) -> list[SlackSink]:
        """Every enabled Slack sink for the workspace, tokens decrypted. A sink whose
        token cannot be decrypted is skipped (logged), never returned half-formed."""

    @abstractmethod
    def deliver(self, sink: SlackSink, message: AlertMessage) -> bool:
        """Deliver to one sink; stamp ``last_delivery_at`` / ``last_error`` on the row.
        Returns True on success. Never raises for an expected delivery failure — a
        failing sink must not break the caller (or the other sinks)."""
