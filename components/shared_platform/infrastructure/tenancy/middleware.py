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

import logging

from django.http import HttpResponseNotFound

from components.shared_platform.infrastructure.tenancy.context import (
    KIND_DEDICATED,
    POOLED_CONTEXT,
    TenantContext,
    bind_tenant,
    reset_tenant,
)

logger = logging.getLogger(__name__)

#: Hosts with no tenant label at all — local dev, health checks, direct IP.
#: These are the pooled console.
_BARE_HOSTS = frozenset({"localhost", "127.0.0.1", "autosec.local", "testserver"})


def _subdomain_of(host: str) -> str:
    """Return the tenant label, or "" when the host carries none."""
    host = host.split(":")[0].strip().lower().rstrip(".")
    if not host or host in _BARE_HOSTS:
        return ""
    labels = host.split(".")
    # "auto-sec.ai" (2 labels) has no tenant label; "senso.auto-sec.ai" does.
    # A bare "autosec" (1 label, e.g. a k8s service name) likewise does not.
    if len(labels) < 3:
        return ""
    return labels[0]


class TenantHostMiddleware:
    """Bind the tenant for the duration of the request, always unbinding after."""

    def __init__(self, get_response):
        self.get_response = get_response

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
            # Must run even when the view raises: a leaked binding would hand
            # the next unit of work on this task the wrong customer.
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
            )
        return TenantContext(kind=POOLED_CONTEXT.kind, tenant_id=str(row.id), subdomain=row.subdomain)
