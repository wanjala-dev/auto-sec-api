"""Unit proofs for the registry → login-brand adapter."""

from __future__ import annotations

import pytest

from components.shared_platform.application.ports.tenant_identity_port import (
    DEFAULT_LOGIN_BRAND_NAME,
)
from components.shared_platform.infrastructure.adapters.tenant_registry_identity_adapter import (
    TenantRegistryIdentityAdapter,
)
from components.shared_platform.infrastructure.tenancy.context import get_current_tenant

pytestmark = [pytest.mark.unit, pytest.mark.unbound_tenancy]


class TestTenantRegistryIdentityAdapter:
    def test_unbound_context_is_the_platform_default_without_a_query(self):
        """No tenant bound → default identity, and NO database access.

        The adapter must return before touching the ORM here: this test runs
        without django_db, so any query would blow up on the missing test
        database — which is exactly the guarantee (the login screen renders
        even before anything is bound).
        """
        assert get_current_tenant() is None
        identity = TenantRegistryIdentityAdapter().current_login_identity()
        assert identity.name == DEFAULT_LOGIN_BRAND_NAME
        assert identity.branded is False
        assert identity.subdomain == ""

    def test_pooled_console_context_is_the_platform_default(self):
        from components.shared_platform.infrastructure.tenancy.context import pooled_context

        with pooled_context():
            identity = TenantRegistryIdentityAdapter().current_login_identity()
        assert identity.name == DEFAULT_LOGIN_BRAND_NAME
        assert identity.branded is False
