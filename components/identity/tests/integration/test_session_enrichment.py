"""Integration tests: session enrichment pipeline (T2-S2).

Login through the real HTTP endpoint creates the session row, then the
``identity.enrich_user_session`` task is run directly (the on-commit
dispatch can't fire inside pytest's wrapped transaction). The UA parse
uses the REAL ``user-agents`` library; geo is exercised both with a
stubbed GeoIP port and with the real adapter's no-mmdb degradation.
"""

from __future__ import annotations

import pytest
from django.urls import reverse
from rest_framework_simplejwt.tokens import RefreshToken

from components.identity.application.ports.geoip_port import GeoIPPort, GeoLocation
from components.identity.application.providers.identity_provider import IdentityProvider
from components.identity.workers.tasks import enrich_user_session
from infrastructure.persistence.users.models import CustomUser, UserSession

pytestmark = pytest.mark.django_db

PASSWORD = "enrich-test-pass-123"
CHROME_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@pytest.fixture(autouse=True)
def disable_security_events_async(settings):
    settings.SECURITY_EVENTS_ASYNC = False


class _StubGeoIP(GeoIPPort):
    def lookup(self, ip):
        return GeoLocation(city="Nairobi", country="Kenya", country_code="KE")


def _make_user(email="enrich-tester@example.com") -> CustomUser:
    user = CustomUser.objects.create_user(email=email, username=email.split("@")[0], password=PASSWORD)
    user.is_verified = True
    user.save(update_fields=["is_verified"])
    return user


def _login_session(api_client, user, **extra) -> UserSession:
    response = api_client.post(reverse("login"), {"email": user.email, "password": PASSWORD}, format="json", **extra)
    assert response.status_code == 200
    jti = str(RefreshToken(response.data["tokens"]["refresh"])["jti"])
    return UserSession.objects.get(refresh_jti=jti)


class TestEnrichTask:
    def test_login_to_enriched_session_end_to_end(self, api_client, monkeypatch):
        monkeypatch.setattr(IdentityProvider, "build_geoip_adapter", staticmethod(_StubGeoIP))
        user = _make_user()
        session = _login_session(
            api_client,
            user,
            HTTP_USER_AGENT=CHROME_MAC,
            HTTP_X_FORWARDED_FOR="41.90.64.10",
        )
        assert session.enriched_at is None

        outcome = enrich_user_session.run(session_id=str(session.id))
        assert outcome == "enriched"

        session.refresh_from_db()
        assert session.device_type == "desktop"
        assert session.browser == "Chrome"
        assert session.browser_version.startswith("126")
        assert session.os == "Mac OS X"
        assert session.geo_city == "Nairobi"
        assert session.geo_country == "Kenya"
        assert session.geo_country_code == "KE"
        assert session.enriched_at is not None

    def test_rerun_overwrites_previous_enrichment(self, api_client, monkeypatch):
        monkeypatch.setattr(IdentityProvider, "build_geoip_adapter", staticmethod(_StubGeoIP))
        user = _make_user("enrich-rerun@example.com")
        session = _login_session(api_client, user, HTTP_USER_AGENT=CHROME_MAC)

        assert enrich_user_session.run(session_id=str(session.id)) == "enriched"
        session.refresh_from_db()
        first_enriched_at = session.enriched_at

        # Simulate stale parsed values, then re-run — task must overwrite.
        UserSession.objects.filter(pk=session.pk).update(browser="StaleBrowser", geo_city="Nowhere")
        assert enrich_user_session.run(session_id=str(session.id)) == "enriched"
        session.refresh_from_db()
        assert session.browser == "Chrome"
        assert session.geo_city == "Nairobi"
        assert session.enriched_at >= first_enriched_at

    def test_real_geoip_adapter_without_mmdb_leaves_geo_blank(self, api_client, settings, tmp_path):
        from components.identity.infrastructure.adapters.maxmind_geoip_adapter import MaxMindGeoIPAdapter

        settings.GEOIP_PATH = str(tmp_path)  # no mmdb inside
        MaxMindGeoIPAdapter.reset_cached_reader()
        try:
            user = _make_user("enrich-nommdb@example.com")
            session = _login_session(
                api_client,
                user,
                HTTP_USER_AGENT=CHROME_MAC,
                HTTP_X_FORWARDED_FOR="41.90.64.10",
            )

            assert enrich_user_session.run(session_id=str(session.id)) == "enriched"
            session.refresh_from_db()
            assert session.device_type == "desktop"  # device facts still land
            assert session.geo_city == ""
            assert session.geo_country == ""
            assert session.enriched_at is not None
        finally:
            MaxMindGeoIPAdapter.reset_cached_reader()

    def test_missing_session_id_is_quiet(self):
        import uuid

        outcome = enrich_user_session.run(session_id=str(uuid.uuid4()))
        assert outcome == "session_missing"
