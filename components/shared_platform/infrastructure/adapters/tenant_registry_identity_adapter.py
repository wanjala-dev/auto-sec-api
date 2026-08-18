"""Tenant registry → login-brand identity (implements TenantIdentityPort).

Reads the tenant the middleware bound for this request and looks up its
display name in the control-plane registry. The registry is a shared app —
the router sends it to ``default`` explicitly — so this works identically for
pooled and dedicated tenants and never touches a tenant database (an empty,
freshly provisioned dedicated tenant still brands its login screen).
"""

from __future__ import annotations

import logging

from components.shared_platform.application.ports.tenant_identity_port import (
    DEFAULT_LOGIN_BRAND_NAME,
    TenantIdentityPort,
    TenantLoginIdentity,
)
from components.shared_platform.infrastructure.tenancy.context import get_current_tenant

logger = logging.getLogger(__name__)

_DEFAULT = TenantLoginIdentity(name=DEFAULT_LOGIN_BRAND_NAME)


class TenantRegistryIdentityAdapter(TenantIdentityPort):
    def current_login_identity(self) -> TenantLoginIdentity:
        context = get_current_tenant()
        if context is None or not context.tenant_id:
            # Bare host / pooled console — the platform default. Identical for
            # every non-tenant request (no existence oracle).
            return _DEFAULT

        from infrastructure.persistence.tenancy.models import Tenant

        row = Tenant.objects.filter(id=context.tenant_id, is_active=True).only("name", "subdomain").first()
        if row is None:
            # The middleware resolved this tenant moments ago; a missing row
            # here means it was deactivated mid-flight. Brand is decoration —
            # degrade to the default rather than erroring the login screen.
            logger.warning("tenant_login_identity_missing tenant_id=%s", context.tenant_id)
            return _DEFAULT

        name = (row.name or "").strip() or row.subdomain
        return TenantLoginIdentity(name=name, subdomain=row.subdomain, branded=True)
