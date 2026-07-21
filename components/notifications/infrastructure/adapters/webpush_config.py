"""Web-push configuration reader (VAPID keys, sender toggle).

Settings access lives here (infrastructure) so the application layer and
controllers stay Django-free. Keys are env-driven and default empty — the
vapid-public-key endpoint truthfully returns "" until ops provisions them.
"""

from __future__ import annotations

from django.conf import settings


def get_vapid_public_key() -> str:
    return getattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", "") or ""


def get_vapid_private_key() -> str:
    return getattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", "") or ""


def get_vapid_admin_email() -> str:
    return getattr(settings, "WEBPUSH_VAPID_ADMIN_EMAIL", "") or ""


def web_push_enabled() -> bool:
    """True only when the T1-S6 sender is switched on for this environment."""
    return bool(getattr(settings, "WEB_PUSH_ENABLED", False))
