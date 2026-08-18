"""Port for the current request's tenant identity (pre-auth safe).

The login screen brands itself by URL: on ``faura.auto-sec.ai`` it should say
"Faura", not "Auto-Sec" (the wanjala login-brand pattern, keyed here by the
Host header the tenancy middleware already resolved). The identity is served
entirely from the control-plane tenant registry — no tenant database is
touched, so an empty, freshly provisioned tenant still brands correctly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

#: What an unbranded (pooled console / bare host) login screen shows.
DEFAULT_LOGIN_BRAND_NAME = "Auto-Sec"


@dataclass(frozen=True)
class TenantLoginIdentity:
    """The pre-auth brand identity of the host serving the request.

    ``branded`` is True only when the request arrived on a registered tenant
    host — the console default is byte-identical for every non-tenant host so
    the endpoint can never become a tenant-existence oracle (unknown
    subdomains already 404 at the middleware, before this port runs).
    """

    name: str
    subdomain: str = ""
    branded: bool = False


class TenantIdentityPort(ABC):
    """Driven port: resolve the bound tenant into a login-brand identity."""

    @abstractmethod
    def current_login_identity(self) -> TenantLoginIdentity:
        """Identity for the currently bound tenant, or the console default."""
        ...
