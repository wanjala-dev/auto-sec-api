"""Phase 0 proofs for tenant routing (ADR 0029).

The first and most important test here watches the router DENY. Everything else
in this file describes behaviour; that one describes the safety property the
whole design rests on, and it is the one that would silently stop holding if
someone "helpfully" added a fallback to `default`.
"""

from __future__ import annotations

import asyncio

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    KIND_POOLED,
    POOLED_CONTEXT,
    TenantContext,
    UnboundTenantError,
    get_current_tenant,
    pooled_context,
    tenant_context,
)
from components.shared_platform.infrastructure.tenancy.middleware import TenantHostMiddleware, _subdomain_of
from components.shared_platform.infrastructure.tenancy.router import TenantRouter
from infrastructure.persistence.tenancy.models import RESERVED_SUBDOMAINS, Tenant

pytestmark = [pytest.mark.unit, pytest.mark.unbound_tenancy]

DEDICATED = TenantContext(kind=KIND_DEDICATED, tenant_id="t-1", subdomain="senso", db_alias="tenant_senso")


class _TenantModel:
    """Stand-in for any workspace-scoped model."""

    class _meta:
        app_label = "findings"
        label = "findings.Finding"


class _SharedModel:
    class _meta:
        app_label = "tenancy"
        label = "tenancy.Tenant"


class _ReferenceModel:
    class _meta:
        app_label = "vuln_intel"
        label = "vuln_intel.EpssScore"


# ── the safety property ────────────────────────────────────────────────────


class TestTheRouterFailsClosed:
    def test_unbound_tenant_RAISES_rather_than_using_default(self):
        """The whole design rests on this.

        The published shape of this router ends with `return "default"`. That
        turns "nobody bound a tenant" into "use the shared database", so a Celery
        task or management command reads and writes real data successfully while
        believing it is scoped. If this test ever fails, tenant isolation is
        gone and nothing else will say so.
        """
        router = TenantRouter()
        assert get_current_tenant() is None

        with pytest.raises(UnboundTenantError) as read:
            router.db_for_read(_TenantModel)
        with pytest.raises(UnboundTenantError):
            router.db_for_write(_TenantModel)

        assert "findings.Finding" in str(read.value)

    def test_shared_apps_resolve_unbound_because_the_registry_must_be_readable(self):
        """Not an exception to fail-closed — the reason it can work at all.

        The middleware queries `tenancy.Tenant` in order to decide what to bind.
        If reading the registry required a binding, resolution would be circular.
        """
        assert TenantRouter().db_for_read(_SharedModel) == "default"

    def test_global_reference_data_resolves_unbound(self):
        """vuln_intel is public fact, identical for every customer (ADR 0029 D9).

        ~280k EPSS rows replicated per tenant would be absurd; it lives in the
        control plane and is joined by CVE string, never by FK.
        """
        assert TenantRouter().db_for_read(_ReferenceModel) == "default"


class TestTheRouterHonoursTheBoundTier:
    def test_pooled_uses_default(self):
        with pooled_context():
            assert TenantRouter().db_for_read(_TenantModel) == "default"

    def test_dedicated_uses_its_own_alias(self):
        with tenant_context(DEDICATED):
            assert TenantRouter().db_for_read(_TenantModel) == "tenant_senso"
            assert TenantRouter().db_for_write(_TenantModel) == "tenant_senso"

    def test_binding_is_undone_even_when_the_body_raises(self):
        """A leaked binding hands the next unit of work the wrong customer."""
        with pytest.raises(RuntimeError), tenant_context(DEDICATED):
            raise RuntimeError("boom")
        assert get_current_tenant() is None


# ── the ASGI trap ──────────────────────────────────────────────────────────


class TestConcurrentTasksDoNotSeeEachOthersTenant:
    """autosec runs on daphne; one thread serves many concurrent requests.

    With `threading.local` — the shape in the inherited middleware and in most
    articles — these two coroutines would share a binding. This test is what
    makes the ContextVar choice a checked fact rather than a comment.
    """

    def test_two_coroutines_keep_separate_tenants(self):
        seen: dict[str, str | None] = {}

        async def run_as(name: str, ctx: TenantContext, pause: float):
            with tenant_context(ctx):
                await asyncio.sleep(pause)  # let the other coroutine interleave
                current = get_current_tenant()
                seen[name] = current.db_alias if current else None

        async def main():
            a = TenantContext(kind=KIND_DEDICATED, tenant_id="a", subdomain="a", db_alias="tenant_a")
            b = TenantContext(kind=KIND_DEDICATED, tenant_id="b", subdomain="b", db_alias="tenant_b")
            await asyncio.gather(run_as("a", a, 0.02), run_as("b", b, 0.01))

        asyncio.run(main())

        assert seen == {"a": "tenant_a", "b": "tenant_b"}
        assert get_current_tenant() is None


# ── host parsing ───────────────────────────────────────────────────────────


class TestSubdomainParsing:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("senso.auto-sec.ai", "senso"),
            ("SENSO.AUTO-SEC.AI", "senso"),
            ("senso.auto-sec.ai:8000", "senso"),
            ("senso.auto-sec.ai.", "senso"),  # trailing dot is legal in DNS
            ("app.auto-sec.ai", "app"),
            ("auto-sec.ai", ""),  # apex carries no tenant label
            ("autosec.local", ""),
            ("localhost:8000", ""),
            ("testserver", ""),
            ("", ""),
            # IP literals carry no tenant claim. The kubelet probes
            # /api/health/ with the pod IP as the Host header; parsing
            # "10.1.2.128" as tenant "10" failed every readiness probe closed.
            ("10.1.2.128:8000", ""),
            ("10.1.2.128", ""),
            ("192.168.65.3", ""),
            ("[::1]:8000", ""),
            ("[2001:db8::1]", ""),
        ],
    )
    def test_label_extraction(self, host, expected):
        assert _subdomain_of(host) == expected


# ── the registry ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestTheRegistry:
    def test_reserved_subdomains_are_rejected(self):
        for reserved in ("app", "www", "api", "admin"):
            with pytest.raises(ValidationError):
                Tenant(subdomain=reserved, name="X").clean()

    def test_reserved_subdomains_are_rejected_by_the_DATABASE_too(self):
        """clean() is not called on bulk paths, and this table is hand-edited."""
        with pytest.raises(IntegrityError), transaction.atomic():
            Tenant.objects.create(subdomain="app", name="Sneaky")

    def test_dedicated_without_an_alias_is_rejected(self):
        with pytest.raises(ValidationError):
            Tenant(subdomain="senso", name="Senso", isolation_mode=KIND_DEDICATED).clean()

    def test_pooled_with_an_alias_is_rejected(self):
        with pytest.raises(ValidationError):
            Tenant(subdomain="senso", name="Senso", isolation_mode=KIND_POOLED, db_alias="tenant_senso").clean()

    def test_subdomain_is_stored_lowercase_or_it_is_unreachable(self):
        t = Tenant.objects.create(subdomain="SENSO", name="Senso")
        t.refresh_from_db()
        assert t.subdomain == "senso"

    def test_reserved_list_covers_the_shared_console(self):
        assert "app" in RESERVED_SUBDOMAINS


# ── middleware resolution ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestHostResolution:
    @staticmethod
    def _resolve(host: str):
        class _Req:
            def get_host(self):
                return host

        return TenantHostMiddleware._resolve(_Req())

    def test_shared_console_binds_pooled(self):
        assert self._resolve("app.auto-sec.ai") == POOLED_CONTEXT

    def test_bare_local_host_binds_pooled(self):
        assert self._resolve("autosec.local") == POOLED_CONTEXT

    def test_ip_literal_host_binds_pooled_so_probes_pass(self):
        """The kubelet addresses the pod by IP — that must never 404."""
        assert self._resolve("10.1.2.128:8000") == POOLED_CONTEXT

    def test_unknown_subdomain_is_refused_not_defaulted(self):
        """Falling through to the console would make a typo act as a tenant."""
        assert self._resolve("nope.auto-sec.ai") is None

    def test_inactive_tenant_is_refused(self):
        Tenant.objects.create(subdomain="senso", name="Senso", is_active=False)
        assert self._resolve("senso.auto-sec.ai") is None

    def test_dedicated_tenant_carries_its_alias(self):
        Tenant.objects.create(subdomain="senso", name="Senso", isolation_mode=KIND_DEDICATED, db_alias="tenant_senso")
        ctx = self._resolve("senso.auto-sec.ai")
        assert ctx.kind == KIND_DEDICATED
        assert ctx.db_alias == "tenant_senso"

    def test_pooled_tenant_on_its_own_subdomain_still_uses_default(self):
        Tenant.objects.create(subdomain="acme", name="Acme")
        ctx = self._resolve("acme.auto-sec.ai")
        assert ctx.kind == KIND_POOLED
        with tenant_context(ctx):
            assert TenantRouter().db_for_read(_TenantModel) == "default"


# ── migrations placement ───────────────────────────────────────────────────


class TestMigrationsGoWhereTheyBelong:
    def test_registry_migrates_only_on_default(self):
        """Otherwise the registry is duplicated into every tenant database."""
        router = TenantRouter()
        assert router.allow_migrate("default", "tenancy") is True
        assert router.allow_migrate("tenant_senso", "tenancy") is False

    def test_tenant_apps_migrate_anywhere(self):
        router = TenantRouter()
        assert router.allow_migrate("default", "findings") is True
        assert router.allow_migrate("tenant_senso", "findings") is True


class TestContextValidation:
    def test_dedicated_requires_an_alias(self):
        with pytest.raises(ValueError):
            TenantContext(kind=KIND_DEDICATED, tenant_id="x", subdomain="x")

    def test_pooled_must_not_carry_an_alias(self):
        with pytest.raises(ValueError):
            TenantContext(kind=KIND_POOLED, db_alias="tenant_x")

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(ValueError):
            TenantContext(kind="silo")
