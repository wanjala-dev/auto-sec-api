"""Per-channel delivery gate — which channels a notification fans out to.

The rule (T1-S5):

* ``realtime`` is ALWAYS on — it is free (a websocket frame to an already
  connected client) and the in-app row it mirrors has already passed the
  recipient/workspace preference funnel.
* ``web_push`` is gated by the user's revived ``push_notifications`` boolean
  (``UserPreference.push_notifications``, off by default).
* ``email`` is gated by the revived ``email_notifications`` boolean
  (``UserPreference.email_notifications``, off by default).

Pure policy — the booleans are read (and cached) by the infrastructure
adapter (``channels_for``); this function only encodes the decision so the
matrix is unit-testable without Django.
"""

from __future__ import annotations

from components.notifications.domain.enums import DeliveryChannel, NotificationType

#: Notification types worth an email (T1-S8). Email is the loudest channel —
#: it interrupts an inbox — so it is reserved for high-value events: direct
#: communication (message), being singled out (mention), a finished artifact
#: (report), and security/system notices. Social ambience (like, comment,
#: follow) and AI chatter (ai_event) stay in-app/push only.
EMAIL_WORTHY_TYPES: frozenset[NotificationType] = frozenset(
    {
        NotificationType.MESSAGE,
        NotificationType.MENTION,
        NotificationType.REPORT,
        NotificationType.SYSTEM,
    }
)


def is_email_worthy(notification_type: str) -> bool:
    """True when ``notification_type`` merits an email fan-out.

    Accepts the raw string value (the funnel carries channel/type values as
    strings across the Celery boundary); unknown types are NOT email-worthy —
    the safe default for a channel that lands in an inbox.
    """
    try:
        resolved = NotificationType(notification_type)
    except ValueError:
        return False
    return resolved in EMAIL_WORTHY_TYPES


def resolve_enabled_channels(
    *,
    push_enabled: bool,
    email_enabled: bool,
) -> tuple[DeliveryChannel, ...]:
    """Return the delivery channels enabled for a recipient, realtime first.

    Order is deterministic (realtime, web_push, email) so callers and tests
    can rely on it.
    """
    channels: list[DeliveryChannel] = [DeliveryChannel.REALTIME]
    if push_enabled:
        channels.append(DeliveryChannel.WEB_PUSH)
    if email_enabled:
        channels.append(DeliveryChannel.EMAIL)
    return tuple(channels)
