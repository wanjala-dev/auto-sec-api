"""Port for the web-push transmitter (T1-S6).

The delivery task pushes an encrypted payload to one device through this
port; infrastructure provides the pywebpush adapter. Errors are typed so
the caller can distinguish a dead device (terminal — expire the
registration, never retry) from a transient push-service failure
(retryable via Celery backoff). The port speaks the standard Web Push
``subscription_info`` dict (``{"endpoint": ..., "keys": {"p256dh", "auth"}}``)
because that shape is protocol-defined (RFC 8291), not vendor-defined.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class WebPushSendError(Exception):
    """Base class for web-push send failures."""


class SubscriptionGoneError(WebPushSendError):
    """The push service says the subscription no longer exists
    (HTTP 404/410). Terminal for the device — expire it, don't retry."""


class TransientPushError(WebPushSendError):
    """Any other send failure (5xx, 429, timeouts, network errors).
    Retryable — the same send may succeed on a later attempt."""


class WebPushSenderPort(ABC):
    """Secondary/driven port for transmitting one web-push message."""

    @abstractmethod
    def send(self, *, subscription_info: dict, payload: str, ttl: int) -> None:
        """Encrypt and POST ``payload`` to the device's push service.

        Raises :class:`SubscriptionGoneError` when the push service reports
        the device registration gone (404/410) and
        :class:`TransientPushError` for every other failure.
        """
        ...
