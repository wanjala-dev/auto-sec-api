"""provision_tenant — the §8 runbook as a command, proven on the pooled path.

The dedicated path's database-level steps (CREATE DATABASE, per-alias migrate)
need a real second Postgres and are exercised operationally (acme, faura,
wanjala on the local cluster); what CI locks down here is everything the
command decides: validation, ordering (registry row last), idempotent
re-runs, the password discipline, and the fail-fast when the connection alias
is missing.
"""

from __future__ import annotations

import pytest
from django.core.management import CommandError, call_command

from infrastructure.persistence.tenancy.models import Tenant
from infrastructure.persistence.users.models import CustomUser, UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

PASSWORD = "Provision2026!"


def _provision(monkeypatch, **overrides):
    monkeypatch.setenv("TENANT_ADMIN_PASSWORD", PASSWORD)
    kwargs = {
        "name": "Wanjala",
        "admin_email": "admin@wanjala.test",
        "workspace_name": "Wanjala",
        "skip_seeds": True,
        "verbosity": 0,
    }
    kwargs.update(overrides)
    call_command("provision_tenant", "wanjala", **kwargs)


class TestPooledProvisioning:
    def test_provisions_registry_admin_and_workspace(self, monkeypatch):
        _provision(monkeypatch)

        row = Tenant.objects.get(subdomain="wanjala")
        assert row.isolation_mode == "pooled"
        assert row.db_alias == ""
        assert row.is_active

        admin = CustomUser.objects.get(email="admin@wanjala.test")
        assert admin.is_verified and admin.is_active
        assert admin.check_password(PASSWORD)

        workspace = Workspace.objects.all_objects().get(id=row.workspace_id)
        assert workspace.workspace_owner_id == admin.id
        assert workspace.status == "active" and workspace.is_active
        assert WorkspaceMembership.objects.filter(
            workspace=workspace, user=admin, role="owner", persona="admin", status="active"
        ).exists()
        assert UserProfile.objects.get(user=admin).active_workspace_id == workspace.id

    def test_rerun_is_idempotent_and_never_rotates_the_password(self, monkeypatch):
        _provision(monkeypatch)
        # Second run with a DIFFERENT env password: nothing duplicates and the
        # existing credential is untouched (seed_demo_workspace discipline).
        monkeypatch.setenv("TENANT_ADMIN_PASSWORD", "Different2026!")
        _provision(monkeypatch)

        assert Tenant.objects.filter(subdomain="wanjala").count() == 1
        assert CustomUser.objects.filter(email="admin@wanjala.test").count() == 1
        assert Workspace.objects.all_objects().filter(workspace_name="Wanjala").count() == 1
        assert CustomUser.objects.get(email="admin@wanjala.test").check_password(PASSWORD)

    def test_seeds_reference_rows(self, monkeypatch):
        from infrastructure.persistence.core.models import FeatureFlag

        _provision(monkeypatch, skip_seeds=False)
        assert FeatureFlag.objects.exists()

    def test_registry_row_lands_last_so_a_failed_run_registers_nothing(self, monkeypatch):
        """Ordering is the safety property: no admin password env → the run
        dies at the seeding step and the subdomain must NOT have been
        registered (a live host pointing at a half-built tenant)."""
        monkeypatch.delenv("TENANT_ADMIN_PASSWORD", raising=False)
        with pytest.raises(CommandError, match="TENANT_ADMIN_PASSWORD"):
            call_command(
                "provision_tenant",
                "wanjala",
                name="Wanjala",
                admin_email="admin@wanjala.test",
                skip_seeds=True,
                verbosity=0,
            )
        assert not Tenant.objects.filter(subdomain="wanjala").exists()


class TestValidation:
    def test_reserved_subdomain_is_refused(self):
        with pytest.raises(CommandError, match="reserved"):
            call_command("provision_tenant", "app", name="App", verbosity=0)

    def test_malformed_subdomain_is_refused(self):
        with pytest.raises(CommandError, match="invalid subdomain"):
            call_command("provision_tenant", "Wanjala.Corp", name="X", verbosity=0)

    def test_conflicting_registry_row_is_refused(self):
        Tenant.objects.create(
            subdomain="wanjala", name="Wanjala", isolation_mode="dedicated", db_alias="tenant_wanjala"
        )
        with pytest.raises(CommandError, match="already registered"):
            call_command("provision_tenant", "wanjala", name="Wanjala", skip_seeds=True, verbosity=0)

    def test_dedicated_without_the_alias_fails_fast_with_the_runbook(self):
        with pytest.raises(CommandError, match="TENANT_DATABASE_URLS"):
            call_command("provision_tenant", "wanjala", name="Wanjala", dedicated=True, skip_seeds=True, verbosity=0)

    def test_workspace_without_admin_is_refused(self):
        with pytest.raises(CommandError, match="--admin-email"):
            call_command("provision_tenant", "wanjala", name="Wanjala", workspace_name="Wanjala", verbosity=0)
