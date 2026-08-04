"""Port: deliver a rendered message to one connected outbound channel (ADR 0016 D1).

Provider-agnostic by construction — the port answers the core's two questions,
*"is this connection reachable?"* and *"deliver this message to it"*, and says
nothing about Slack, Teams, or SMTP. Adapters (one per ``kind``) own auth,
formatting, and rate limits; the notifications funnel owns what/when/how safely.

Deliberately NOT on this port: reading connections out of the database. The
predecessor (``AlertSinkPort.enabled_slack_sinks``) fused "query the DB and
decrypt secrets" with "talk to Slack", which made every adapter a repository
too. Resolution lives in ``DeliveryConnectionRepository``; adapters receive an
already-resolved :class:`ResolvedDeliveryConnection` and stay pure I/O.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar
from uuid import UUID


@dataclass(frozen=True)
class ResolvedDeliveryConnection:
    """A connection ready to use — secret already decrypted, config flattened.

    Framework-free: adapters never touch the ORM row. ``secret`` holds whatever
    the ``auth_mode`` implies (an incoming-webhook URL, or a bot token); it is a
    bearer credential either way and must never be logged or echoed.
    """

    id: UUID
    kind: str
    auth_mode: str
    secret: str
    name: str = ""
    channel: str = ""
    min_severity: str = "high"
    events: tuple[str, ...] = ()


@dataclass(frozen=True)
class DeliveryMessage:
    """A channel-agnostic message — the adapter renders it for its target.

    Carries notification-grade summary only (ADR 0016 D6): title, body lines,
    severity, an absolute deep link, and flat label/value fields. Never prompts,
    tool output, raw finding payloads, log lines, or secrets — a channel's
    membership is invisible to us, so treat every message as world-readable.
    """

    title: str
    body: str
    severity: str = ""
    link: str = ""
    fields: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DeliveryHealth:
    """Outcome of a reachability probe. ``detail`` is human-readable, never secret."""

    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    """Outcome of one delivery attempt.

    ``retry_after_seconds`` carries a provider's explicit backoff instruction
    (Slack answers 429 with ``Retry-After``); the sender task honours it over its
    own backoff. ``permanent`` marks a deterministic failure — a revoked webhook,
    a bad token — which must be recorded as failed and NOT retried.
    """

    ok: bool
    detail: str = ""
    retry_after_seconds: int | None = None
    permanent: bool = False


class DeliveryChannelPort(ABC):
    """One implementation per provider kind; registered by ``KIND``."""

    KIND: ClassVar[str]

    @abstractmethod
    def verify(self, connection: ResolvedDeliveryConnection) -> DeliveryHealth:
        """Probe the connection and report reachability.

        Implementations may send a real test message when the provider offers no
        side-effect-free probe (an incoming webhook has none). Never raises for an
        expected failure — an unreachable destination is a ``DeliveryHealth(ok=False)``.
        """

    @abstractmethod
    def deliver(self, connection: ResolvedDeliveryConnection, message: DeliveryMessage) -> DeliveryResult:
        """Deliver one message.

        Never raises for an expected delivery failure: a dead destination must not
        break the caller, the emitting pipeline, or the other connections. Health
        stamping is the repository's job, not the adapter's.
        """
