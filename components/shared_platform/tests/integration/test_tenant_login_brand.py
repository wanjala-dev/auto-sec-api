"""The pre-auth login brand endpoint — the URL identifies the tenant.

``/tenant/login-brand/`` lets the login screen on ``faura.auto-sec.ai`` say
"Faura" instead of "Auto-Sec". The properties under test:

* the identity comes from the Host header alone (no auth, no params);
* it is served ENTIRELY from the control-plane registry — a dedicated
  tenant whose database alias does not even exist still brands correctly;
* every non-tenant host receives the byte-identical platform default
  (no tenant-existence oracle);
* unknown subdomains die at the middleware (404) before the view runs.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.tenancy.models import Tenant

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

LOGIN_BRAND = "/api/v1/tenant/login-brand/"

DEFAULT_PAYLOAD = {"name": "Auto-Sec", "subdomain": "", "branded": False}


class TestTenantLoginBrand:
    def test_bare_host_serves_platform_default(self, client):
        response = client.get(LOGIN_BRAND)
        assert response.status_code == 200
        assert response.json() == DEFAULT_PAYLOAD

    def test_reserved_subdomain_serves_platform_default(self, client):
        response = client.get(LOGIN_BRAND, HTTP_HOST="app.auto-sec.ai")
        assert response.status_code == 200
        assert response.json() == DEFAULT_PAYLOAD

    def test_tenant_host_serves_registry_name(self, client):
        Tenant.objects.create(subdomain="faura", name="Faura Security")
        response = client.get(LOGIN_BRAND, HTTP_HOST="faura.auto-sec.ai")
        assert response.status_code == 200
        assert response.json() == {"name": "Faura Security", "subdomain": "faura", "branded": True}

    def test_dedicated_tenant_brands_without_touching_its_database(self, client):
        """The registry is the only source — the tenant DB is never opened.

        The alias below is deliberately absent from ``settings.DATABASES``:
        if anything on this request path issued a tenant-scoped query, the
        router would route it to a connection that does not exist and the
        request would 500. A fresh, empty dedicated tenant must still brand
        its login screen.
        """
        Tenant.objects.create(
            subdomain="acme",
            name="Acme Corp",
            isolation_mode="dedicated",
            db_alias="tenant_acme_not_in_settings",
        )
        response = client.get(LOGIN_BRAND, HTTP_HOST="acme.auto-sec.ai")
        assert response.status_code == 200
        assert response.json() == {"name": "Acme Corp", "subdomain": "acme", "branded": True}

    def test_blank_registry_name_falls_back_to_subdomain(self, client):
        Tenant.objects.create(subdomain="faura", name="  ")
        response = client.get(LOGIN_BRAND, HTTP_HOST="faura.auto-sec.ai")
        assert response.json() == {"name": "faura", "subdomain": "faura", "branded": True}

    def test_unknown_subdomain_404s_before_the_view(self, client):
        response = client.get(LOGIN_BRAND, HTTP_HOST="ghost.auto-sec.ai")
        assert response.status_code == 404

    def test_inactive_tenant_404s_like_an_unknown_one(self, client):
        Tenant.objects.create(subdomain="faura", name="Faura Security", is_active=False)
        response = client.get(LOGIN_BRAND, HTTP_HOST="faura.auto-sec.ai")
        assert response.status_code == 404

    def test_root_alias_parity(self, client):
        """The unversioned root mount serves the same payload as /api/v1/."""
        response = client.get("/tenant/login-brand/")
        assert response.status_code == 200
        assert response.json() == DEFAULT_PAYLOAD
