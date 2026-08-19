"""Enumerating the tenants a scheduled sweep must visit.

Celery Beat is the one entry point the tenancy design never got a binder for
(skill §3i lists HTTP, WebSocket, Celery *dispatch*, management commands and
inbound webhooks — beat is absent from that table because beat dispatches with
nothing bound). A beat-fired task therefore arrives unbound, and the fail-closed
router refuses its first query.

That is not a theoretical hole. Verified on the live cluster 2026-08-19:
``DATABASE_ROUTERS`` is registered, four aliases are configured
(``default`` + three dedicated tenants), and an unbound
``AwsOrganizationConnection.objects.count()`` raises ``UnboundTenantError``.
27 of the 28 scheduled tasks queried tenant-routed models unbound.

**Absence of a binder was only half the bug.** Binding every sweep to the pooled
console would stop the crash and leave a quieter defect behind: dedicated-tier
tenants live in their own databases, so a pooled-only sweep would never scan
their accounts, never expire their sessions, never run their workflows — while
every log line read "completed". The whole point of this module is that a
scheduled sweep visits EVERY tenant, and says how many it visited.

The registry read here is legitimately unbound: ``tenancy`` is in
``SHARED_APP_LABELS`` precisely so tenant resolution is not circular.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: The pooled console. Always swept, and always first: it is where the large
#: majority of customers live (tenancy skill §2a — pooled is the permanent home
#: of almost everyone, not a staging area), so a partial failure later in the
#: list must not be what stops the pool from being swept.
POOLED_LABEL = "pooled"
POOLED_ALIAS = "default"


@dataclass(frozen=True)
class TenantScope:
    """One database a scheduled sweep must run against, and how to bind it."""

    label: str
    db_alias: str

    @property
    def is_pooled(self) -> bool:
        return self.db_alias == POOLED_ALIAS

    @contextmanager
    def bind(self) -> Iterator[None]:
        """Bind this scope for the duration of the block, and unbind after."""
        from components.shared_platform.infrastructure.tenancy.context import (
            KIND_DEDICATED,
            TenantContext,
            pooled_context,
            tenant_context,
        )

        if self.is_pooled:
            with pooled_context():
                yield
            return
        with tenant_context(TenantContext(kind=KIND_DEDICATED, subdomain=self.label, db_alias=self.db_alias)):
            yield


def sweep_scopes() -> list[TenantScope]:
    """Every scope a periodic sweep must visit: the pool, then each dedicated tenant.

    Inactive tenants are skipped — deactivation is an access control at the
    middleware (skill invariant 5), and it would be incoherent for background
    work to keep operating on a customer whose front door returns 404.

    A dedicated tenant whose ``db_alias`` is not in ``settings.DATABASES`` is
    skipped WITH A WARNING rather than raising: that combination means the
    registry row landed before the deploy config did (the documented ordering of
    the provisioning runbook, skill §8 step 2), and one half-provisioned tenant
    must not stop every other tenant's sweep. It is loud because a tenant that
    silently stops being swept is exactly the failure this module exists to end.
    """
    from django.conf import settings

    from infrastructure.persistence.tenancy.models import Tenant

    scopes = [TenantScope(label=POOLED_LABEL, db_alias=POOLED_ALIAS)]
    configured = set(settings.DATABASES)

    rows = Tenant.objects.filter(is_active=True).exclude(db_alias="").order_by("subdomain")
    for row in rows.values_list("subdomain", "db_alias"):
        subdomain, alias = row
        if alias == POOLED_ALIAS:
            # A pooled tenant shares `default`, which is already scope #1.
            continue
        if alias not in configured:
            logger.warning(
                "tenant_sweep_scope_skipped subdomain=%s db_alias=%s reason=alias_not_in_DATABASES "
                "(registry row exists but the connection string is not deployed — this tenant is "
                "NOT being swept)",
                subdomain,
                alias,
            )
            continue
        scopes.append(TenantScope(label=subdomain, db_alias=alias))

    return scopes
