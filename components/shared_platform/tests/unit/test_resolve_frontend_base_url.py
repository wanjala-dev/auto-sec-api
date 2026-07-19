"""Unit tests for ``resolve_frontend_base_url``.

The resolver builds the base URL used inside transactional emails (invite
links, password setup, etc.). It MUST prefer the explicit frontend URL
settings over the Django ``Site`` domain — in prod the Site domain is the
API host (``api.wanjala.art``) while the frontend lives at a separate
CloudFront URL. Mixing them up sends users to dead /invite/accept routes
on the API host. See email-invite base URL bug fix (April 2026).
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from components.shared_platform.infrastructure.services.core_utils import (
    resolve_frontend_base_url,
)


@override_settings(
    EMAIL_CLICK_REDIRECT_LINK="https://frontend.example.com",
    LOCALHOST_FRONTEND_URL="https://frontend.example.com",
)
def test_settings_frontend_url_wins_over_site_domain():
    """Site domain (the API host) must NEVER override the frontend URL."""
    base = resolve_frontend_base_url(site_domain="api.wanjala.art")
    assert base == "https://frontend.example.com"


@override_settings(
    EMAIL_CLICK_REDIRECT_LINK=None,
    LOCALHOST_FRONTEND_URL=None,
)
def test_falls_back_to_site_domain_when_no_frontend_settings():
    base = resolve_frontend_base_url(site_domain="example.org")
    assert base == "https://example.org"


@override_settings(
    EMAIL_CLICK_REDIRECT_LINK=None,
    LOCALHOST_FRONTEND_URL=None,
)
def test_falls_back_to_localhost_when_nothing_configured():
    base = resolve_frontend_base_url(site_domain="")
    assert base == "https://localhost:3000"


@override_settings(
    EMAIL_CLICK_REDIRECT_LINK="https://frontend.example.com/EmailConfirmed/",
    LOCALHOST_FRONTEND_URL=None,
)
def test_strips_path_component_from_settings_url():
    base = resolve_frontend_base_url(site_domain="api.example.com")
    assert base == "https://frontend.example.com"


@override_settings(
    EMAIL_CLICK_REDIRECT_LINK=None,
    LOCALHOST_FRONTEND_URL="http://localhost:3000",
)
def test_localhost_frontend_url_used_when_email_redirect_missing():
    base = resolve_frontend_base_url(site_domain="api.wanjala.art")
    assert base == "http://localhost:3000"


@override_settings(
    FRONTEND_URL="https://app.octopusintl.org",
    # Stale legacy vars still pointing at the OLD CloudFront host — the exact
    # state that lingers after a frontend-domain move if .env isn't fully
    # cleaned up.
    LOCALHOST_FRONTEND_URL="https://d2wnv83yfoz6nw.cloudfront.net",
    EMAIL_CLICK_REDIRECT_LINK="https://d2wnv83yfoz6nw.cloudfront.net",
)
def test_frontend_url_wins_over_stale_cloudfront_vars():
    """GO-LIVE GUARD: FRONTEND_URL is the single source of truth for every
    user-facing email CTA (login magic-link, password reset, email verify,
    invites, receipt requests). After the frontend moved to
    app.octopusintl.org, a stale LOCALHOST_FRONTEND_URL / EMAIL_CLICK_REDIRECT_LINK
    left pointing at the old CloudFront host must NOT win — otherwise those
    email buttons send users to the dead old domain.
    """
    assert resolve_frontend_base_url() == "https://app.octopusintl.org"


@override_settings(
    FRONTEND_URL="https://app.octopusintl.org/",  # trailing slash (common in .env)
    LOCALHOST_FRONTEND_URL=None,
    EMAIL_CLICK_REDIRECT_LINK=None,
)
def test_frontend_url_trailing_slash_is_normalized():
    """A trailing slash in FRONTEND_URL must not produce '//path' in CTA links."""
    assert resolve_frontend_base_url() == "https://app.octopusintl.org"
