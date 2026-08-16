"""Tenancy scoping for OTHER contexts — the application-layer front door.

The binding primitives live in shared_platform's infrastructure
(``tenancy/context.py``), and the cross-context rule is absolute: no context
imports another's infrastructure (zero allowlist). Any context that must run
code outside a request — a boot-time seed in ``ready()``, a CLI path that
predates the management-command wrapper — binds through THIS provider
instead.

Only the pooled scope is offered here deliberately. Binding a *specific*
tenant is a routing decision that belongs to the entry-point seams
(middleware, Celery signals, webhook resolvers, the provisioning runbook) —
handing every context a bind-any-tenant primitive would invite exactly the
ad-hoc scoping this subsystem exists to end.
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
