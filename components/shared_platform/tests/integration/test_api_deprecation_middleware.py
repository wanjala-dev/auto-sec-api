"""Integration tests for ApiDeprecationMiddleware.

As of Phase 3 of the versioning roadmap, v0 is marked deprecated in the real
settings (``API_DEPRECATED_VERSIONS``), so the middleware stamps the RFC 9745
(``Deprecation``) + RFC 8594 (``Sunset``) + migration-guide ``Link`` headers on
BOTH the explicit ``/api/v0/`` mount AND the unversioned root alias — but NOT on
``/api/v1/`` (the committed successor) nor on infra routes (health, schema,
Swagger, admin).

Headers are stamped regardless of the view's status code (the deprecation signal
must reach the client even on 401/403), so these tests assert header presence
without needing auth or seeded data.
"""

import pytest

# A v0 config whose sunset is already in the past — drives the 410 enforcement.
# (The live settings sunset is 2027, so these tests must override to simulate
# "after sunset" without time-travel.)
_SUNSET_PASSED_CONFIG = {
    "v0": {
        "deprecation": "2020-01-01T00:00:00Z",
        "sunset": "2020-06-01T00:00:00Z",
        "successor": "/api/v1/",
        "link": "https://github.com/wanjala-dev/api-v0.2.0/blob/development/api-v2.0/docs/api/migrating-v0-v1.md",
    },
}


@pytest.mark.django_db
class TestApiDeprecationMiddleware:
    """v0 is deprecated in the live config; v1 + infra are untouched."""

    def test_explicit_v0_mount_gets_headers(self, api_client):
        response = api_client.get("/api/v0/sectors/")
        assert response.has_header("Deprecation")
        assert response.has_header("Sunset")
        assert response["Deprecation"].startswith("@")
        assert 'rel="successor-version"' in response["Link"]
        assert "/api/v1/" in response["Link"]

    def test_unversioned_root_alias_gets_headers(self, api_client):
        # NEW in Phase 3: the unversioned root alias resolves to DEFAULT_VERSION
        # ('v0'), which is deprecated — so it is now stamped too.
        response = api_client.get("/sectors/")
        assert response.has_header("Deprecation")
        assert response.has_header("Sunset")
        assert 'rel="successor-version"' in response["Link"]

    def test_v1_mount_is_not_stamped(self, api_client):
        # /api/v1/ carries version='v1', which is not in the config -> skipped.
        response = api_client.get("/api/v1/sectors/")
        assert not response.has_header("Deprecation")
        assert not response.has_header("Sunset")

    def test_header_values_match_the_config(self, api_client):
        # Sunset corresponds to 2027-06-19 (the 12-month window).
        response = api_client.get("/api/v0/sectors/")
        assert response["Sunset"].endswith("GMT")
        assert "2027" in response["Sunset"]
        # Link carries the migration-guide rel="deprecation" pointer.
        assert 'rel="deprecation"' in response["Link"]
        assert "migrating-v0-v1" in response["Link"]

    @pytest.mark.parametrize("infra_path", ["/api/health/", "/"])
    def test_infra_routes_are_not_stamped(self, api_client, infra_path):
        # Health and Swagger (root '') share the root with the unversioned alias
        # but are non-API-contract infra — never deprecated.
        response = api_client.get(infra_path)
        assert not response.has_header("Deprecation")
        assert not response.has_header("Sunset")


@pytest.mark.django_db
class TestApiSunsetEnforcement:
    """Once a deprecated version's sunset date has passed, the surface returns
    410 Gone (Phase 4) instead of being served. Same scope as the header
    stamping: /api/v0/ + the root alias; never /api/v1/ or infra."""

    @pytest.fixture(autouse=True)
    def _sunset_in_the_past(self, settings):
        # pytest-django's `settings` fixture auto-reverts after each test.
        settings.API_DEPRECATED_VERSIONS = _SUNSET_PASSED_CONFIG

    def test_explicit_v0_mount_returns_410(self, api_client):
        response = api_client.get("/api/v0/sectors/")
        assert response.status_code == 410
        body = response.json()
        assert body["error_code"] == "ApiVersionSunset"
        assert body["successor"] == "/api/v1/"
        assert "migrating-v0-v1" in body["migration_guide"]
        # The RFC headers ride the 410 too.
        assert response.has_header("Deprecation")
        assert response.has_header("Sunset")

    def test_unversioned_root_alias_returns_410(self, api_client):
        response = api_client.get("/sectors/")
        assert response.status_code == 410
        assert response.json()["error_code"] == "ApiVersionSunset"

    def test_v1_mount_is_served_not_410(self, api_client):
        # v1 isn't in the config, so it's never sunset.
        response = api_client.get("/api/v1/sectors/")
        assert response.status_code != 410

    @pytest.mark.parametrize("infra_path", ["/api/health/", "/"])
    def test_infra_routes_are_not_410(self, api_client, infra_path):
        response = api_client.get(infra_path)
        assert response.status_code != 410

    def test_no_leak_in_410_body(self, api_client):
        body = api_client.get("/api/v0/sectors/").content.decode()
        assert "sk_test" not in body and "secret" not in body.lower()


# Webhook / ingest URLs registered with external systems (Stripe, Plaid, SES).
# These must stay version-stable: never deprecation-stamped, never 410'd at the
# v0 sunset — on the root alias AND on any /api/vN/ mount.
_WEBHOOK_PATHS = [
    "/sponsorship/donations/stripe/webhook/",        # Stripe donation webhook (alias)
    "/api/v0/sponsorship/donations/stripe/webhook/",  # …same, explicit v0 mount
    "/sponsorship/donations/payments/ingest/",        # payments ingest
]


@pytest.mark.django_db
class TestWebhookVersionExemption:
    """External-system webhook/ingest surfaces are exempt from the deprecation
    lifecycle entirely — they are version-stable by contract with Stripe/Plaid/
    SES, so deprecating or 410'ing one would silently break live payments."""

    @pytest.mark.parametrize("webhook_path", _WEBHOOK_PATHS)
    def test_webhook_is_not_deprecation_stamped(self, api_client, webhook_path):
        # Live config: v0 is deprecated, but webhooks never carry the headers.
        response = api_client.post(webhook_path)
        assert not response.has_header("Deprecation")
        assert not response.has_header("Sunset")

    @pytest.mark.parametrize("webhook_path", _WEBHOOK_PATHS)
    def test_webhook_is_not_410_after_sunset(self, api_client, webhook_path, settings):
        # Even with a past-sunset config (which 410s /sectors/), webhooks survive.
        settings.API_DEPRECATED_VERSIONS = _SUNSET_PASSED_CONFIG
        response = api_client.post(webhook_path)
        assert response.status_code != 410
