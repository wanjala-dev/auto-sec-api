"""Resolve the tenant from the request host and bind it for the request.

    senso.auto-sec.ai → Tenant(subdomain="senso") → its database
    app.auto-sec.ai   → the shared console        → default, workspace-scoped

Note what the host does and does not decide. For a **dedicated** tenant the host
identifies the customer, so it picks the connection. On the **pooled** console
the host identifies only the tier — many customers live there and the workspace
separates them, exactly as today. So `app.` binds an explicit pooled marker
rather than leaving the context empty: "nothing bound" has to keep meaning
*error* (ADR 0029 D4), or the fail-closed guarantee is worth nothing.
"""

from __future__ import annotations

import ipaddress
import logging

from django.http import HttpResponseForbidden, HttpResponseNotFound

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    POOLED_CONTEXT,
    TenantContext,
    bind_tenant,
    reset_tenant,
)
from components.shared_platform.infrastructure.tenancy.workspace_context import (
    bind_workspace,
    reset_workspace,
)

logger = logging.getLogger(__name__)

#: Hosts with no tenant label at all — local dev, health checks, direct IP.
#: These are the pooled console.
_BARE_HOSTS = frozenset({"localhost", "127.0.0.1", "autosec.local", "testserver"})


def _subdomain_of(host: str) -> str:
    """Return the tenant label, or "" when the host carries none."""
    host = host.strip().lower().rstrip(".")
    if host.startswith("["):
        # Bracketed IPv6 literal ("[::1]:8000") — an address, never a tenant.
        return ""
    host = host.split(":")[0]
    if not host or host in _BARE_HOSTS:
        return ""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        # An IP literal says where the request went, not who it is for — it
        # carries no tenant claim. Kubelet probes and pod-to-pod traffic
        # address the pod by IP; parsing "10.1.2.128" as tenant "10" made
        # every readiness probe fail closed and took the rollout down.
        return ""
    labels = host.split(".")
    # "auto-sec.ai" (2 labels) has no tenant label; "senso.auto-sec.ai" does.
    # A bare "autosec" (1 label, e.g. a k8s service name) likewise does not.
    if len(labels) < 3:
        return ""
    return labels[0]


class TenantHostMiddleware:
    """Bind the tenant for the duration of the request, always unbinding after.

    Also binds the **workspace** in ``process_view``, which is the earliest
    point Django has resolved the URL and can hand us ``workspace_id`` — 72 URL
    patterns carry ``workspaces/<uuid:workspace_id>/``, so that one hook covers
    the workspace-scoped surface.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Bind the workspace from the resolved URL, and enforce host agreement.

        The enforcement is the security value the host binding actually buys.
        Without it a subdomain is decoration: a token for workspace A used
        against ``senso.auto-sec.ai`` would be served happily. With it the host
        becomes a second, independent check on which customer's data a request
        may touch — one a stolen or mis-scoped token does not satisfy.

        The token goes on the REQUEST, never on ``self``: a middleware instance
        is shared by every request in the process, so per-request state stored
        on it leaks across requests — the exact bug this subsystem exists to
        prevent.
        """
        workspace_id = view_kwargs.get("workspace_id")
        if workspace_id is None:
            return None

        pinned = getattr(request, "tenant", None)
        if pinned is not None and pinned.workspace_id and str(pinned.workspace_id) != str(workspace_id):
            logger.warning(
                "tenant_host_workspace_mismatch host_workspace=%s requested_workspace=%s subdomain=%s",
                pinned.workspace_id,
                workspace_id,
                pinned.subdomain,
            )
            return HttpResponseForbidden("This workspace is not available on this host.")

        request._workspace_token = bind_workspace(workspace_id)
        return None

    def __call__(self, request):
        context = self._resolve(request)
        if context is None:
            # Fail closed: an unknown or inactive subdomain must NOT fall
            # through to the shared console. Falling through would let a typo'd
            # or unregistered host behave as the default tenant. 404 rather than
            # 403 — do not confirm which subdomains exist.
            return HttpResponseNotFound("Organization not found.")

        request.tenant = context
        token = bind_tenant(context)
        try:
            return self.get_response(request)
        finally:
            # Both bindings must be released even when the view raises; a leaked
            # binding hands the next unit of work on this task the wrong tenant
            # or the wrong workspace.
            workspace_token = getattr(request, "_workspace_token", None)
            if workspace_token is not None:
                reset_workspace(workspace_token)
                request._workspace_token = None
            reset_tenant(token)

    @staticmethod
    def _resolve(request) -> TenantContext | None:
        from infrastructure.persistence.tenancy.models import RESERVED_SUBDOMAINS, Tenant

        label = _subdomain_of(request.get_host())
        if not label or label in RESERVED_SUBDOMAINS:
            return POOLED_CONTEXT

        # Reading the registry needs no bound tenant — `tenancy` is a shared app
        # in the router, which is what stops this being circular.
        row = (
            Tenant.objects.filter(subdomain=label, is_active=True)
            .only("id", "subdomain", "isolation_mode", "db_alias")
            .first()
        )
        if row is None:
            logger.warning("tenant_host_unresolved subdomain=%s", label)
            return None

        if row.isolation_mode == KIND_DEDICATED:
            return TenantContext(
                kind=KIND_DEDICATED,
                tenant_id=str(row.id),
                subdomain=row.subdomain,
                db_alias=row.db_alias,
                workspace_id=str(row.workspace_id) if row.workspace_id else None,
            )
        return TenantContext(
            kind=POOLED_CONTEXT.kind,
            tenant_id=str(row.id),
            subdomain=row.subdomain,
            workspace_id=str(row.workspace_id) if row.workspace_id else None,
        )
