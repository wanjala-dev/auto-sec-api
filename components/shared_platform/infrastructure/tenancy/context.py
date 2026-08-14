"""The current tenant, for the duration of one request or one task.

**A `ContextVar`, not a `threading.local`.** autosec runs on daphne + channels
(`ASGI_APPLICATION = "api.asgi.application"`). Under ASGI one thread serves many
concurrent requests through the event loop, so a thread-local tenant is not
merely stale — request A's tenant becomes visible to request B on the same
thread. `ContextVar` is scoped to the async task, which is the correct
granularity, and behaves correctly under sync/WSGI too. See the `tenancy` skill
§3a; the inherited `TenantMiddleware` got this wrong.

**What is stored is a value object, never the ORM row.** The router calls
:func:`get_current_tenant` on every query. If that returned a lazily-loaded
``Tenant`` model instance, resolving it would itself issue a query, which would
re-enter the router — so the binding boundary loads the row once and stores
plain data.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

#: The shared console — many tenants in one database, separated by workspace.
KIND_POOLED = "pooled"
#: One customer, one database.
KIND_DEDICATED = "dedicated"


class UnboundTenantError(RuntimeError):
    """Raised when tenant-scoped data is touched with no tenant bound.

    This is the fail-closed guarantee (ADR 0029 D4). It is deliberately loud:
    the alternative — quietly resolving to ``default`` — means any path that
    forgets to bind reads and writes real data successfully while believing it
    is scoped. A traceback is cheap; a silent cross-tenant write is not.
    """


@dataclass(frozen=True)
class TenantContext:
    """Everything the router needs, resolved once at the binding boundary."""

    kind: str
    #: ``None`` on the pooled console — there, the host identifies the tier, not
    #: a specific customer; the workspace does that.
    tenant_id: str | None = None
    subdomain: str = ""
    db_alias: str | None = None
    #: The workspace this subdomain is pinned to, when it is pinned to one.
    #: Stored BY VALUE, never as an FK: a dedicated tenant's Workspace row lives
    #: in that tenant's database, and Django cannot span databases.
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in (KIND_POOLED, KIND_DEDICATED):
            raise ValueError(f"unknown tenant kind: {self.kind!r}")
        if self.kind == KIND_DEDICATED and not self.db_alias:
            raise ValueError("a dedicated tenant must carry a db_alias")
        if self.kind == KIND_POOLED and self.db_alias:
            raise ValueError("a pooled tenant must not carry a db_alias — it uses default")


#: Default is ``None`` = nothing bound = the router raises. That is the point.
_current: ContextVar[TenantContext | None] = ContextVar("autosec_current_tenant", default=None)

POOLED_CONTEXT = TenantContext(kind=KIND_POOLED)


def get_current_tenant() -> TenantContext | None:
    return _current.get()


def bind_tenant(context: TenantContext) -> Token:
    """Bind *context* for the current task. Caller MUST reset with the token."""
    return _current.set(context)


def set_tenant(context: TenantContext | None) -> Token:
    """Bind *context*, or explicitly bind NOTHING.

    Binding to ``None`` is a real operation, not a no-op: at a boundary that
    reuses a process — a Celery prefork child running up to 50 tasks — "leave
    it alone" means "inherit whatever the last unit of work left", which is a
    cross-tenant read waiting to happen. Setting unconditionally makes each
    unit start from a known state.
    """
    return _current.set(context)


def reset_tenant(token: Token) -> None:
    _current.reset(token)


@contextmanager
def tenant_context(context: TenantContext) -> Iterator[TenantContext]:
    """Bind a tenant for a block, and unbind it even if the block raises.

    The `finally` is the whole point: an exception that escaped without
    resetting would leave the next unit of work on this task bound to the wrong
    customer.
    """
    token = bind_tenant(context)
    try:
        yield context
    finally:
        reset_tenant(token)


@contextmanager
def pooled_context() -> Iterator[TenantContext]:
    """Bind the shared console explicitly.

    Used by management commands, the shared-tier request path, and anything that
    legitimately operates on the pooled database. Explicit because "no tenant
    bound" must keep meaning *error*, not *default* — if pooled were the
    fallback, the fail-closed guarantee would be worth nothing.
    """
    with tenant_context(POOLED_CONTEXT) as ctx:
        yield ctx
