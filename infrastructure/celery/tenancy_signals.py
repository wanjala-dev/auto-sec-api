"""Carry the tenant and workspace across the queue.

A task has no request, so it has no host and no URL — the two things the
middleware binds from. That is the gap ADR 0029 D6 names, and it is the reason
the inherited design was unsafe rather than merely wrong: a thread-local set by
middleware is simply absent in a worker, so a router that falls back to
``default`` writes every background job into the control plane while looking
scoped.

The fix belongs at the **dispatch boundary**, not in the router:

    .delay() ──> before_task_publish ──> headers carry tenant + workspace
                                              │
                                        (queue, another process)
                                              │
                 task_prerun <────────────────┘  bind from headers
                     …task body runs bound…
                 task_postrun ─────────────────> unbind

Headers rather than kwargs on purpose: every existing task keeps its signature,
92 of them, none of which need editing. And a task dispatched before this
shipped simply arrives with no headers, which binds nothing — so it fails
closed rather than silently running against the wrong customer.
"""

from __future__ import annotations

import logging
from typing import Any

from celery.signals import before_task_publish, task_postrun, task_prerun

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    KIND_POOLED,
    TenantContext,
    get_current_tenant,
    reset_tenant,
    set_tenant,
)
from components.shared_platform.infrastructure.tenancy.workspace_context import (
    get_current_workspace,
    reset_workspace,
    set_workspace,
)

logger = logging.getLogger("celery.tenancy")

#: Header keys. Prefixed so they cannot collide with Celery's own protocol
#: fields or an application's custom headers.
_TENANT_HEADER = "autosec_tenant"
_WORKSPACE_HEADER = "autosec_workspace"

#: task_id -> (tenant_token, workspace_token), so postrun can unbind exactly
#: what prerun bound. Keyed by task id because a worker may interleave tasks.
_tokens: dict[str, tuple[Any, Any]] = {}


@before_task_publish.connect
def _stamp_tenancy(headers: dict | None = None, **_kwargs: Any) -> None:
    """Record the dispatcher's tenant + workspace onto the outgoing message."""
    if headers is None:
        return

    tenant = get_current_tenant()
    if tenant is not None:
        headers[_TENANT_HEADER] = {
            "kind": tenant.kind,
            "tenant_id": tenant.tenant_id,
            "subdomain": tenant.subdomain,
            "db_alias": tenant.db_alias,
            "workspace_id": tenant.workspace_id,
        }

    workspace_id = get_current_workspace()
    if workspace_id is not None:
        headers[_WORKSPACE_HEADER] = workspace_id


def _context_from(payload: dict) -> TenantContext | None:
    kind = payload.get("kind")
    if kind not in (KIND_POOLED, KIND_DEDICATED):
        return None
    try:
        return TenantContext(
            kind=kind,
            tenant_id=payload.get("tenant_id"),
            subdomain=payload.get("subdomain") or "",
            db_alias=payload.get("db_alias"),
            workspace_id=payload.get("workspace_id"),
        )
    except ValueError:
        # A malformed header binds nothing rather than binding something wrong.
        logger.warning("celery_tenancy_header_invalid payload=%s", payload)
        return None


@task_prerun.connect
def _bind_tenancy(task_id: str, task: Any, **_kwargs: Any) -> None:
    """Bind what the dispatcher stamped — and ALWAYS bind, even to nothing.

    A prefork child is long-lived: with ``worker_max_tasks_per_child=50`` it
    runs up to fifty tasks before being recycled. So binding only when a header
    is present is not "leaving it alone", it is **inheriting** — a task
    dispatched without headers would run under whatever tenant the previous
    task on this process left behind. Setting unconditionally makes each task
    start from a known state, and an unstamped task then correctly hits the
    fail-closed path instead of silently borrowing someone else's customer.
    """
    request = getattr(task, "request", None)

    context = None
    payload = getattr(request, _TENANT_HEADER, None) if request else None
    if isinstance(payload, dict):
        context = _context_from(payload)

    workspace_id = getattr(request, _WORKSPACE_HEADER, None) if request else None

    # set(), not "set only if we have something" — see the docstring.
    tenant_token = set_tenant(context)
    workspace_token = set_workspace(workspace_id or None)
    _tokens[task_id] = (tenant_token, workspace_token)


@task_postrun.connect
def _unbind_tenancy(task_id: str, **_kwargs: Any) -> None:
    """Release the bindings. Fires on success AND failure, which is the point.

    Belt and braces with the unconditional bind in prerun: if this were ever
    missed — a handler exception, a signal that did not fire — the next task
    still starts from a known state rather than inheriting.
    """
    tokens = _tokens.pop(task_id, None)
    if not tokens:
        return
    tenant_token, workspace_token = tokens
    if workspace_token is not None:
        reset_workspace(workspace_token)
    if tenant_token is not None:
        reset_tenant(tenant_token)
