"""Bind the tenant for a WebSocket connection — channels bypasses HTTP middleware.

Every entry point that touches the ORM binds the tenant, or the router raises
(fail closed). HTTP binds in ``TenantHostMiddleware``, Celery in the task
signals, management commands in ``run_management_command()``. WebSockets run
through channels' own ASGI stack, which never executes Django's ``MIDDLEWARE``
— left unbound, the JWT handshake's user lookup is the first query and every
connection dies with ``UnboundTenantError`` before a consumer even runs.

This is the WS twin of ``TenantHostMiddleware``: resolve the tenant from the
Host header through the same ``resolve_tenant_context`` (one resolution path,
one fail-closed behaviour), refuse unknown subdomains with close code 4404,
bind for the lifetime of the connection, clear on the way out. It must wrap
the OUTSIDE of the stack — auth runs inside it, because auth already needs
the database.

Context mechanics: this middleware is pure async, so ``set_tenant`` writes
into the connection task's own context; the consumer and every
``database_sync_to_async`` hop it makes (asgiref copies the current context
into the worker thread) see the binding, and concurrent connections — each
its own task — cannot see each other's.
"""

from __future__ import annotations

import logging

from components.shared_platform.infrastructure.tenancy.context import set_tenant
from components.shared_platform.infrastructure.tenancy.middleware import resolve_tenant_context
from components.shared_platform.infrastructure.tenancy.workspace_context import set_workspace

logger = logging.getLogger(__name__)

#: Close codes mirror the HTTP responses (4000 + status, the convention the
#: consumers already use for 4401/4403): unknown subdomain → the HTTP 404,
#: host pinned to a different workspace → the HTTP 403.
CLOSE_UNKNOWN_TENANT = 4404
CLOSE_WORKSPACE_MISMATCH = 4403


def _host_of(scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"host":
            return value.decode("latin-1")
    return ""


def tenant_allows_workspace(scope, workspace_id) -> bool:
    """False when the connection's host is pinned to a DIFFERENT workspace.

    The WS twin of the ``process_view`` enforcement: a token for workspace A
    used against ``senso.auto-sec.ai`` must be refused, or the subdomain is
    decoration. Workspace-scoped consumers call this before their membership
    check and close with ``CLOSE_WORKSPACE_MISMATCH`` when it fails.
    """
    context = scope.get("tenant")
    if context is None or not context.workspace_id:
        return True
    return str(context.workspace_id) == str(workspace_id)


class TenantBindWebsocketMiddleware:
    """Resolve the tenant from the WS Host header; bind it for the connection."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "websocket":
            return await self.inner(scope, receive, send)

        from channels.db import database_sync_to_async

        host = _host_of(scope)
        context = await database_sync_to_async(resolve_tenant_context)(host)
        if context is None:
            # Fail closed, mirroring the HTTP 404: an unknown or inactive
            # subdomain must not fall through to the shared console — and a
            # 4404 close does not confirm which subdomains exist.
            logger.warning("ws_tenant_host_unresolved host=%s", host)
            message = await receive()
            if message.get("type") == "websocket.connect":
                await send({"type": "websocket.close", "code": CLOSE_UNKNOWN_TENANT})
            return None

        scope["tenant"] = context
        set_tenant(context)
        try:
            return await self.inner(scope, receive, send)
        finally:
            # Clear, never token-reset (tenancy skill §3h) — and clear even
            # when the consumer raises, or the next unit of work on this
            # context inherits the wrong tenant or workspace.
            set_workspace(None)
            set_tenant(None)
