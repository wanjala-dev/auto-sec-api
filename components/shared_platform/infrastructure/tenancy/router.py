"""Database router: the bound tenant selects the connection (ADR 0029).

NOT REGISTERED YET. ``DATABASE_ROUTERS`` is still empty; this class is proven by
its tests and wired in a later phase. Registering it before every binding
boundary exists (Celery dispatch, management commands, webhook entry) would make
every unbound path raise — which is fail-closed working exactly as designed, and
would take the application down. The wiring order is: bind everywhere, then
register.

The shape most articles publish is::

    def db_for_read(self, model, **hints):
        tenant = get_current_tenant()
        if tenant:
            return f"tenant_{tenant.id}"
        return "default"          # ← the bug

That final line is why the inherited router was dangerous. It turns "nobody
bound a tenant" into "use the shared database", so a Celery task, a management
command, a signal outside a request or a shell session all read and write real
data successfully while believing they are scoped. Absence of a tenant must
never resolve to a database.
"""

from __future__ import annotations

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    UnboundTenantError,
    get_current_tenant,
)

#: Apps that live in the control-plane database and are legitimately readable
#: with no tenant bound.
#:
#: ``tenancy`` MUST be here: the middleware queries the registry in order to
#: work out which tenant to bind, so requiring a binding to read it would be
#: circular.
#:
#: The rest are either Django's own plumbing or GLOBAL REFERENCE DATA — public
#: facts owned by no tenant (ADR 0029 D9). ``vuln_intel`` is the load-bearing
#: example: EPSS scores and the CISA KEV catalog are ~280k rows that are
#: identical for every customer, and replicating them per tenant would be
#: absurd. Reference data is joined BY VALUE (on the CVE string), never by a
#: ForeignKey — an FK from tenant data into a shared table cannot span databases
#: and would block the split outright.
#: THE MEMBERSHIP RULE — the shared set must be FK-CLOSED: no tenant-routed
#: model may hold a ForeignKey/M2M into a shared app, because that FK cannot
#: span databases. The first `migrate --database=tenant_acme` proved the point
#: (2026-08-16): `auth` was listed here, so `auth_group` existed only in
#: `default`, and creating `users_customuser_groups` in the tenant database
#: failed on the dangling FK. Django's contrib apps all FK each other (users →
#: auth → contenttypes; flatpages/socialaccount → sites; admin → users), so
#: they are tenant-routed: present in `default` for the pool AND in every
#: dedicated database — each dedicated tenant gets its own groups,
#: permissions, content types and sessions, which is exactly what "your own
#: database" means. Enforced by
#: tests/architecture/test_tenancy_boundaries.py::TestTheSharedSetIsFkClosed.
SHARED_APP_LABELS = frozenset(
    {
        "tenancy",
        "vuln_intel",
    }
)


class TenantRouter:
    """Route by the bound tenant; raise when nothing is bound."""

    # ── read / write ────────────────────────────────────────────────────────

    def db_for_read(self, model, **hints):
        return self._alias_for(model)

    def db_for_write(self, model, **hints):
        return self._alias_for(model)

    @staticmethod
    def _alias_for(model) -> str:
        if model._meta.app_label in SHARED_APP_LABELS:
            return "default"

        context = get_current_tenant()
        if context is None:
            raise UnboundTenantError(
                f"No tenant bound while accessing {model._meta.label}. "
                "Bind one explicitly — pooled_context() for the shared console, "
                "tenant_context(...) for a specific customer. Falling back to "
                "'default' here would be a silent cross-tenant access."
            )

        if context.kind == KIND_DEDICATED:
            return context.db_alias
        return "default"

    # ── relations ───────────────────────────────────────────────────────────

    def allow_relation(self, obj1, obj2, **hints):
        """Permit a relation only when both objects live on the same connection.

        Returning ``True`` unconditionally (the inherited behaviour) tells Django
        a cross-database relation is fine when it is not — Django cannot enforce
        such a foreign key, so the breakage surfaces later as corrupt reads
        rather than as an error at the point of the mistake.
        """
        db1 = getattr(obj1, "_state", None) and obj1._state.db
        db2 = getattr(obj2, "_state", None) and obj2._state.db
        if db1 and db2:
            return db1 == db2
        return None

    # ── migrations ──────────────────────────────────────────────────────────

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Shared apps migrate on ``default`` only; tenant apps everywhere else.

        Without this the registry gets duplicated into every tenant database and
        the tenant tables get created in the control plane — both of which make
        the control-plane invariant (D9) false the first time a dedicated tenant
        is provisioned.
        """
        if app_label in SHARED_APP_LABELS:
            return db == "default"
        return True
