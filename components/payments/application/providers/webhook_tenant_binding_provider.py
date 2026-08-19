"""Tenant binding for inbound payment-provider webhooks (tenancy skill §3d).

A payment provider POSTs to ONE fixed URL. There is no tenant subdomain on
that request, so ``TenantHostMiddleware`` binds the shared (pooled) console —
correct for a pooled customer, wrong for a dedicated one. The owning database
has to be resolved FROM THE PAYLOAD (the connected-account id) and bound
explicitly before anything is written.

This module is the payments context's front door onto that binding. It does
two things and nothing else:

* ``resolve_webhook_tenant_alias`` — ask which configured database owns a
  connected account (a cross-alias ``.using()`` scan; no binding involved).
* ``webhook_tenant_scope`` — bind that database for a block of work, via
  shared_platform's sanctioned ``integration_callback_scope``. Passing
  ``None`` is an explicit no-op that keeps whatever the request already
  bound — an unknown account must never be silently steered anywhere.

WHY A BINDING AND NOT A ``.using()``: a webhook handler runs a whole use-case
graph — record + claim the event, then the provider-specific processing, each
with its own repositories. Threading an alias through every one of them is the
shape that rots; one binding around the whole unit of work is the shape that
holds. The predecessor of this module was
``shared_platform...tenant_middlewares.set_db_for_router()``, which wrote a
``threading.local`` the live ContextVar-based ``TenantRouter`` never reads:
it looked exactly like this and bound nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


def resolve_webhook_tenant_alias(account_id: str | None) -> str | None:
    """Return the database alias that owns ``account_id``, or ``None``.

    ``None`` means "no configured database claims this connected account" —
    an unknown account, or a platform (non-Connect) event that carries none.
    Callers must treat it as "do not rebind", never as "use the pool".
    """
    if not account_id:
        return None

    from components.payments.infrastructure.adapters.payment_utils import (
        resolve_db_alias_for_stripe_account,
    )

    return resolve_db_alias_for_stripe_account(account_id)


def resolve_platform_webhook_tenant(event: object):
    """Which database owns the workspace a PLATFORM billing event is about.

    The sibling of :func:`resolve_webhook_tenant_alias`, for the other half of
    the problem. That one answers "who owns this connected account?" and is
    useless for platform events, which carry no account — only a customer, a
    subscription, and (on checkout) our own ``workspace_id`` metadata. Until
    this existed, the ONLY mounted Stripe route — the platform subscription
    webhook — resolved no alias at all, so a dedicated tenant's own billing
    event was handled against the pool, found no workspace there, and was
    marked ignored with a 200. Stripe was told "handled"; nothing was.

    Returns a routing verdict rather than a bare alias because "unresolved"
    has to be actionable: the caller must be able to distinguish an event that
    names nothing routable (fine, nothing to bind) from a money-moving event
    whose owner could not be found (a billing outage that must be reported to
    the provider as retryable, never silently swallowed).
    """
    from components.payments.infrastructure.adapters.payment_utils import (
        resolve_db_alias_for_platform_billing_event,
    )

    return resolve_db_alias_for_platform_billing_event(event)


def webhook_write_alias() -> str:
    """The DB alias the currently-bound tenant writes payment events to.

    Open the webhook's transaction on this, not on ``default``: under the
    tenant router a bare ``atomic()`` transacts ``default`` while the writes
    go to the bound tenant's database.
    """
    from components.payments.infrastructure.adapters.payment_utils import (
        payment_event_write_alias,
    )

    return payment_event_write_alias()


@contextmanager
def webhook_tenant_scope(db_alias: str | None) -> Iterator[None]:
    """Bind ``db_alias`` for the block; no-op when it is ``None``.

    The alias must have been derived from data the SIGNED payload matched
    (or from an endpoint-configuration hint that the signature check then
    confirms) — never from unverified client input.
    """
    if not db_alias:
        yield
        return

    from components.shared_platform.application.providers.tenancy_scopes_provider import (
        integration_callback_scope,
    )

    with integration_callback_scope(db_alias):
        yield
