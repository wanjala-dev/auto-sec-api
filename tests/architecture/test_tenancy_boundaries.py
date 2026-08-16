"""Fitness functions for the tenancy boundary (ADR 0029).

Skill §9: each guard lands beside the code it guards. These encode the two
invariants that are cheap to hold now and expensive to retrofit — and that a
reviewer cannot reliably catch by reading a diff.
"""

from __future__ import annotations

import pytest
from django.apps import apps

from components.shared_platform.infrastructure.tenancy.router import SHARED_APP_LABELS

pytestmark = pytest.mark.arch


#: The one model allowed to name a workspace while living in the control plane.
#:
#: ``Tenant.workspace_id`` is ROUTING METADATA, not customer data: it records
#: which workspace a subdomain serves so a request on that host can be refused
#: if it asks for a different one. The control plane must know it in order to
#: route at all — that is its job — and it carries no customer-owned content,
#: just a pointer. Stored as a bare UUID rather than a ForeignKey precisely
#: because the Workspace row it names may live in another database.
#:
#: The distinction this encodes: a POINTER the control plane needs is fine; a
#: COPY of anything the customer owns is not. Widening this exemption is how
#: D9 erodes, so any addition needs the same paragraph of justification.
_CONTROL_PLANE_POINTERS = {"tenancy.Tenant"}


def _has_workspace_relation(model) -> bool:
    return any(f.name in ("workspace", "workspace_id") for f in model._meta.get_fields())


class TestTheControlPlaneHoldsNoCustomerData:
    """ADR 0029 D9 — the invariant that keeps the self-hosted tier reachable.

    Anything routed to ``default`` lives in the control plane. If customer-owned
    rows go there, BYOC stops being a connection-string change and becomes a
    data migration out of the control plane — and the way that happens is
    incremental: a cross-tenant search index, a shared audit table, a reporting
    rollup, each individually reasonable.

    A workspace FK is the tell. Global reference data (``vuln_intel`` — EPSS,
    KEV) has none, which is exactly why it belongs here and is joined by CVE
    string rather than by ForeignKey.
    """

    def test_no_shared_app_carries_a_workspace_relation(self):
        offenders = []
        for label in sorted(SHARED_APP_LABELS):
            try:
                config = apps.get_app_config(label)
            except LookupError:
                continue  # not installed in this settings module — fine
            for model in config.get_models():
                dotted = f"{label}.{model.__name__}"
                if dotted in _CONTROL_PLANE_POINTERS:
                    continue
                if _has_workspace_relation(model):
                    offenders.append(dotted)

        assert not offenders, (
            "These models are routed to the control-plane database but carry a "
            f"workspace relation, i.e. customer data in `default`: {offenders}. "
            "Either the model is not shared (remove its app from "
            "SHARED_APP_LABELS), or this is a deliberate decision to abandon the "
            "self-hosted tier (ADR 0029 D9) — which must be taken explicitly."
        )

    def test_the_registry_is_shared_and_the_tenant_data_is_not(self):
        """The registry must resolve unbound, or tenant resolution is circular."""
        assert "tenancy" in SHARED_APP_LABELS
        # Findings, workspaces and users are tenant-owned and must NOT be here.
        for tenant_owned in ("findings", "workspaces", "users", "project", "agents"):
            assert tenant_owned not in SHARED_APP_LABELS, (
                f"'{tenant_owned}' holds customer data and must route to the tenant's database, not the control plane."
            )


class TestTheSharedSetIsFkClosed:
    """No tenant-routed model may FK/M2M into a shared app — the FK cannot
    span databases.

    Proven the hard way on the first `migrate --database=tenant_acme`
    (2026-08-16): `auth` was in SHARED_APP_LABELS, so `auth_group` existed
    only in `default`, and creating `users_customuser_groups` in the tenant
    database failed on the dangling FK. Django's contrib apps FK each other
    (users → auth → contenttypes; flatpages/socialaccount → sites; admin →
    users), which is why the shared set is just the registry and by-value
    reference data. Shared apps stay reachable from tenant data only BY VALUE
    (the CVE string into vuln_intel, the bare-UUID workspace pointer on
    tenancy.Tenant) — never by ForeignKey.
    """

    def test_no_tenant_routed_model_fks_into_a_shared_app(self):
        offenders = []
        for model in apps.get_models(include_auto_created=True):
            if model._meta.app_label in SHARED_APP_LABELS:
                continue
            for field in model._meta.get_fields():
                if not getattr(field, "is_relation", False) or field.related_model is None:
                    continue
                if field.auto_created and not field.concrete:
                    continue  # reverse accessor — counted from the owning side
                if field.related_model._meta.app_label in SHARED_APP_LABELS:
                    offenders.append(f"{model._meta.label}.{field.name} -> {field.related_model._meta.label}")

        assert not offenders, (
            "These tenant-routed relations point into a shared (default-only) "
            f"app and cannot span databases: {offenders}. Either the target app "
            "is not really shared (remove it from SHARED_APP_LABELS) or the "
            "relation must become a by-value join (store the natural key, no FK)."
        )


class TestTheRouterCannotQuietlyFailOpen:
    """The fallback that makes every unbound path a silent cross-tenant access.

    The published shape of this router ends `return "default"`. Re-adding it
    would keep every test green except the ones that assert the denial — so this
    guards the source text as well, because the failure is one line and reads
    as harmless.
    """

    def test_the_router_source_has_no_bare_default_fallback(self):
        import inspect

        from components.shared_platform.infrastructure.tenancy import router

        source = inspect.getsource(router.TenantRouter._alias_for)
        assert "raise UnboundTenantError" in source, (
            "TenantRouter._alias_for no longer raises on an unbound tenant. "
            "Absence of a tenant must never resolve to a database (ADR 0029 D4)."
        )


class TestTheTenancyMiddlewareWrapsEverythingThatTouchesTheDatabase:
    """Ordering bug, found by deploying (2026-08-14).

    Middleware runs top→bottom on the request and bottom→top on the response.
    The tenancy middleware unbinds in a `finally`, so anything ABOVE it in the
    list runs its response phase AFTER the tenant is already gone — and
    ``FlatpageFallbackMiddleware`` queries ``FlatPage`` exactly there.

    Placed low, it 500'd every request including ``/api/health/``, so the pod
    never became ready. The router was right; the ordering was wrong. Nothing in
    a diff makes that visible, which is why it is asserted here.
    """

    #: Middleware known to hit the ORM in either phase.
    _DB_TOUCHING = (
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.flatpages.middleware.FlatpageFallbackMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    )

    def test_it_is_listed_before_every_db_touching_middleware(self):
        from django.conf import settings

        chain = list(settings.MIDDLEWARE)
        tenancy = "components.shared_platform.infrastructure.tenancy.middleware.TenantHostMiddleware"
        assert tenancy in chain, "TenantHostMiddleware is not installed."

        position = chain.index(tenancy)
        too_early = [m for m in self._DB_TOUCHING if m in chain and chain.index(m) < position]

        assert not too_early, (
            f"These middleware run outside the tenant binding: {too_early}. "
            "Anything that touches the ORM must sit BELOW TenantHostMiddleware, "
            "or its response phase executes after the tenant is unbound and the "
            "router raises — which is what took the pod down on 2026-08-14."
        )
