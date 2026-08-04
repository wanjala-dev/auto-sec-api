"""Composition root for outbound delivery channels (ADR 0016 D1/D8).

Mirrors ``LogSourceProvider`` — a ``kind -> adapter`` registry that knows which
concrete adapters exist and which are enabled. Adding the Nth provider is an
adapter + one line here + a ``DeliveryConnection.Kind`` value; routing, noise
control, redaction, ledger, and retry are inherited from the notifications funnel
and solved once.

Nascent adapters register behind feature flags and **fail closed** — a flag
service outage must never silently enable an unvetted delivery path.
"""

from __future__ import annotations

from collections.abc import Mapping

from components.integrations.application.ports.delivery_channel_port import DeliveryChannelPort

DeliveryAdapters = dict[str, DeliveryChannelPort]


class UnsupportedDeliveryChannelError(Exception):
    """No adapter is registered (or enabled) for the requested channel kind."""


class DeliveryChannelProvider:
    """Resolves a connection ``kind`` to the adapter that can deliver to it."""

    def __init__(self, adapters: Mapping[str, DeliveryChannelPort] | None = None):
        self._adapters: DeliveryAdapters = dict(adapters or self._default_adapters())

    @staticmethod
    def _default_adapters() -> DeliveryAdapters:
        from components.integrations.infrastructure.adapters.slack_delivery_adapter import SlackDeliveryAdapter

        adapters: DeliveryAdapters = {SlackDeliveryAdapter.KIND: SlackDeliveryAdapter()}

        # Generic webhook (ADR 0016 D8) ships in P2 behind the shared SSRF guard.
        # Teams / Discord / SMTP follow the same shape. Each registers here behind
        # its own flag; until then the kind resolves to UnsupportedDeliveryChannelError,
        # which is the correct fail-closed behaviour for a security product.
        return adapters

    def get(self, kind: str) -> DeliveryChannelPort:
        adapter = self._adapters.get((kind or "").strip().lower())
        if adapter is None:
            raise UnsupportedDeliveryChannelError(f"No enabled delivery adapter for kind={kind!r}")
        return adapter

    def kinds(self) -> tuple[str, ...]:
        """The kinds a workspace can actually connect right now — drives the API's
        accepted-kind validation and the Settings panel's picker."""
        return tuple(self._adapters.keys())


_PROVIDER: DeliveryChannelProvider | None = None


def get_delivery_channel_provider() -> DeliveryChannelProvider:
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = DeliveryChannelProvider()
    return _PROVIDER


def get_delivery_connection_repository():
    """The resolver/stamper the funnel leg and the CRUD/verify endpoints share."""
    from components.integrations.infrastructure.repositories.delivery_connection_repository import (
        DeliveryConnectionRepository,
    )

    return DeliveryConnectionRepository()


def get_delivery_connection_service():
    """Composition root for the connection lifecycle (list/create/update/delete/verify)."""
    from components.integrations.application.delivery_connection_service import (
        DeliveryConnectionService,
    )
    from components.integrations.application.providers.secret_envelope_provider import (
        decrypt_secret,
        encrypt_secret,
    )

    return DeliveryConnectionService(
        _repo=get_delivery_connection_repository(),
        _resolve_adapter=lambda kind: get_delivery_channel_provider().get(kind),
        _encrypt=encrypt_secret,
        _decrypt=decrypt_secret,
    )


def enabled_delivery_kinds() -> tuple[str, ...]:
    """Kinds a workspace can connect today — drives the Settings picker and the API's
    accepted-kind check, so the two can never disagree."""
    return get_delivery_channel_provider().kinds()
