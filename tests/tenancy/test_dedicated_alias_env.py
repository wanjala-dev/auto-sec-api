"""TENANT_DATABASE_URLS → extra DATABASES aliases (the dedicated tier's knob).

Provisioning a dedicated tenant is an operational action (tenancy skill §8):
create the database, add its URL to this env var, insert the registry row,
migrate the alias. These tests pin the parsing contract — especially that
`default` can never be redefined through it (ADR 0029 D9: the control-plane
connection comes only from DATABASE_URL).
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from api.settings.base import tenant_databases_from_env


class TestTenantDatabasesFromEnv:
    def test_a_mapping_becomes_database_aliases(self):
        parsed = tenant_databases_from_env(
            '{"tenant_acme": "postgres://app:pw@postgres:5432/tenant_acme",'
            ' "tenant_globex": "postgres://app:pw@postgres:5432/tenant_globex"}'
        )
        assert set(parsed) == {"tenant_acme", "tenant_globex"}
        assert parsed["tenant_acme"]["ENGINE"] == "django.db.backends.postgresql"
        assert parsed["tenant_acme"]["NAME"] == "tenant_acme"
        assert parsed["tenant_acme"]["HOST"] == "postgres"

    def test_unset_or_blank_means_no_extra_aliases(self):
        assert tenant_databases_from_env("") == {}
        assert tenant_databases_from_env("   ") == {}
        assert tenant_databases_from_env(None) == {}

    def test_invalid_json_fails_loudly_not_silently_poolless(self):
        with pytest.raises(ImproperlyConfigured):
            tenant_databases_from_env("{not json")

    def test_a_json_list_is_rejected(self):
        with pytest.raises(ImproperlyConfigured):
            tenant_databases_from_env('["postgres://x"]')

    def test_default_can_never_be_redefined(self):
        """Silently replacing the control-plane connection with a tenant's
        would be the quietest possible cross-tenant incident."""
        with pytest.raises(ImproperlyConfigured):
            tenant_databases_from_env('{"default": "postgres://app:pw@postgres:5432/evil"}')
