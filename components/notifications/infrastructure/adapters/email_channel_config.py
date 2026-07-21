"""Email-channel configuration reader (T1-S8).

Settings access lives here (infrastructure) so the application layer and
workers stay Django-free — same pattern as ``webpush_config``. The flag is
env-driven and defaults off: the ledger records pending email deliveries
either way; ``NOTIF_EMAIL_CHANNEL_ENABLED`` flips the actual sender on.
"""

from __future__ import annotations

from django.conf import settings


def notification_email_enabled() -> bool:
    """True only when the T1-S8 email sender is switched on for this environment."""
    return bool(getattr(settings, "NOTIF_EMAIL_CHANNEL_ENABLED", False))
