"""pywebpush adapter implementing WebPushSenderPort (T1-S6).

The pywebpush SDK lives HERE and nowhere else — the delivery task talks to
the port via the provider. VAPID material comes from ``webpush_config``
(env-driven settings reader in this same infrastructure layer).

Error mapping:

    WebPushException w/ response 404 or 410  -> SubscriptionGoneError
    WebPushException (any other / no status) -> TransientPushError
    requests network errors (conn/timeout)   -> TransientPushError

pywebpush only raises ``WebPushException`` for non-2xx *responses*; raw
``requests`` exceptions (connection refused, DNS, timeout) propagate
untouched, so both branches are mapped explicitly.
"""

from __future__ import annotations

import logging

from components.notifications.application.ports.web_push_sender_port import (
    SubscriptionGoneError,
    TransientPushError,
    WebPushSenderPort,
)

logger = logging.getLogger(__name__)

_GONE_STATUS_CODES = (404, 410)


class PywebpushWebPushSenderAdapter(WebPushSenderPort):
    """Concrete sender backed by ``pywebpush.webpush``."""

    def send(self, *, subscription_info: dict, payload: str, ttl: int) -> None:
        # Deferred imports keep module load SDK-free (house style in this
        # context) and let flag-off environments run without pywebpush
        # installed until the image is rebuilt with the new requirement.
        import requests
        from pywebpush import WebPushException, webpush

        from components.notifications.infrastructure.adapters.webpush_config import (
            get_vapid_admin_email,
            get_vapid_private_key,
        )

        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=get_vapid_private_key(),
                # Fresh dict per call — pywebpush mutates the claims
                # (adds aud/exp) in place.
                vapid_claims={"sub": f"mailto:{get_vapid_admin_email()}"},
                ttl=ttl,
            )
        except WebPushException as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code in _GONE_STATUS_CODES:
                raise SubscriptionGoneError(f"push service returned {status_code} for subscription") from exc
            raise TransientPushError(f"web push send failed status={status_code}") from exc
        except requests.RequestException as exc:
            raise TransientPushError(f"web push network error: {type(exc).__name__}") from exc
