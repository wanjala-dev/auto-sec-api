"""Tenancy scoping for OTHER contexts — the application-layer front door.

The binding primitives live in shared_platform's infrastructure
(``tenancy/context.py``), and the cross-context rule is absolute: no context
imports another's infrastructure (zero allowlist). Any context that must run
code outside a request — a boot-time seed in ``ready()``, a CLI path that
predates the management-command wrapper — binds through THIS provider
instead.

Two scopes are offered here deliberately, and no bind-any-tenant primitive.
Binding a *specific* tenant is a routing decision that belongs to the
entry-point seams (middleware, Celery signals, webhook resolvers, the
provisioning runbook) — handing every context a general bind primitive would
invite exactly the ad-hoc scoping this subsystem exists to end.
``integration_callback_scope`` below IS one of those entry-point seams: the
payload-based binding an inbound webhook resolver performs (tenancy skill
§3d/§3i), keyed by the db alias the resolver's cross-alias scan found.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def pooled_scope() -> Iterator[None]:
    """Bind the shared (pooled) console for the duration of the block.

    Use for work that legitimately runs with no request and no task
    context — e.g. seeding pool-wide catalog rows at process boot. The
    fail-closed router refuses unbound queries; this is the sanctioned way
    for another context to say "I mean the pool".
    """
    from components.shared_platform.infrastructure.tenancy.context import pooled_context

    with pooled_context():
        yield


def scheduled_sweep_scopes() -> list:
    """Every tenant scope a periodic (beat) sweep must visit — an entry-point seam.

    Beat is a binding boundary in exactly the sense the module docstring above
    describes: it dispatches with no request, no host and no tenant, so the
    routing decision has to be made HERE rather than left to each of the ~28
    scheduled tasks. That is the same reasoning that put the management-command
    binding in ``manage.py`` instead of in 99 command classes.

    Returns ``TenantScope`` objects, each with a ``bind()`` context manager and a
    ``label``. This is deliberately NOT the bind-any-tenant primitive the module
    docstring refuses to offer: the caller cannot name a tenant, it can only
    iterate the full set that the registry says exists.
    """
    from components.shared_platform.infrastructure.tenancy.sweep import sweep_scopes

    return sweep_scopes()


@contextmanager
def integration_callback_scope(db_alias: str) -> Iterator[None]:
    """Bind the tenant that owns ``db_alias`` for an inbound integration callback.

    Inbound webhooks (Stripe, GitHub) arrive on one fixed URL with no tenant
    host — the handler resolves the owning database FROM THE PAYLOAD (a
    cross-alias ``.using(alias)`` scan, the ``resolve_db_alias_for_stripe_account``
    shape) and binds it here for the per-tenant work. ``"default"`` binds the
    pooled console; any other alias binds that dedicated database. This is
    payload-based entry-point binding (tenancy skill §3d), NOT a general
    bind-any-tenant primitive — callers must have derived the alias from data a
    signed/verified payload matched, never from client-chosen input.
    """
    from components.shared_platform.infrastructure.tenancy.context import (
        KIND_DEDICATED,
        TenantContext,
        pooled_context,
        tenant_context,
    )

    alias = (db_alias or "").strip()
    if not alias or alias == "default":
        with pooled_context():
            yield
        return
    with tenant_context(TenantContext(kind=KIND_DEDICATED, db_alias=alias)):
        yield
