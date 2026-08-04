"""Config reader for the external delivery channel (ADR 0016 D7).

Mirrors ``email_channel_config`` — one place that answers "is this channel switched
on in this environment", so the sender task can make a *truthful* no-op instead of
pretending it delivered.

Defaults ON: a workspace has to connect a channel and subscribe to events before
anything is sent, so the setting exists as an operator kill switch for the whole
external leg (an incident, a noisy deploy), not as the feature's on-ramp.
"""

from __future__ import annotations

from django.conf import settings


def external_delivery_enabled() -> bool:
    return bool(getattr(settings, "NOTIF_EXTERNAL_CHANNEL_ENABLED", True))
