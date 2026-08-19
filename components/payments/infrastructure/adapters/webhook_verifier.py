from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.payments.application.providers import make_payment_gateway_provider
from components.payments.domain.errors import WebhookVerificationError
from components.payments.infrastructure.adapters.payment_utils import resolve_db_alias_for_stripe_account
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.payments.models import WorkspacePaymentMethod


@dataclass(frozen=True)
class LegacyWebhookVerificationResult:
    event: Any
    method: WorkspacePaymentMethod | None
    workspace: Workspace | None
    account_id: str | None
    legacy_context: object | None
    provider_slug: str
    api_key: str | None
    #: The database alias that owns the connected account this event belongs
    #: to, or ``None`` when the event names no account (a platform event) or
    #: no configured database claims it. Resolution only — the CALLER binds
    #: it, because the binding has to outlive this call and cover every write
    #: the webhook triggers.
    db_alias: str | None = None
    #: ``False`` when the event verified but must NOT enter the idempotency
    #: ledger — the Connect/platform cross-delivery guard below. Recording it
    #: would make the correct endpoint dedupe-skip the same ``event_id``.
    recordable: bool = True


class LegacyIncomingWebhookVerifier:
    """Transitional verifier that keeps the old webhook contract while delegating into payments components.

    READ-ONLY BY CONSTRUCTION. This used to also record + claim the
    ``PaymentEvent`` idempotency row, which meant the money-path write
    happened inside verification — before any caller had a chance to bind the
    tenant that owns the event. It called ``set_db_for_router(db_alias)`` to
    cover that, and that function wrote a ``threading.local`` the live
    ContextVar-based ``TenantRouter`` never reads, so the write landed in
    whatever database the REQUEST bound (the pool, since webhooks arrive on a
    fixed URL with no tenant subdomain).

    The intake now belongs to the caller, which runs it inside
    ``webhook_tenant_scope(db_alias)``. Keeping this method free of writes is
    what makes that ordering possible: verification may run under the request's
    own binding because it only reads, and every write happens after the owning
    alias is known.
    """

    @staticmethod
    def _extract_stripe_event_account(event: object) -> str | None:
        if isinstance(event, dict):
            return event.get("account")
        return getattr(event, "account", None)

    def verify(self, request, endpoint_name: str | None = None) -> LegacyWebhookVerificationResult:
        force_platform_webhook = endpoint_name == "team_subscriptions"
        account_id = request.META.get("HTTP_STRIPE_ACCOUNT") or request.GET.get("account")
        db_alias: str | None = None
        if account_id and not force_platform_webhook:
            # Endpoint-configuration hint (our own ``?account=`` / header
            # convention). Stripe itself puts the connected account in the
            # signed event body, handled below.
            db_alias = resolve_db_alias_for_stripe_account(account_id)

        gateway_provider = make_payment_gateway_provider()
        for provider_slug, gateway in gateway_provider.registered_gateways():
            if not gateway:
                continue

            methods = (
                WorkspacePaymentMethod.objects.select_related("workspace", "provider")
                .prefetch_related("webhooks")
                .filter(
                    provider__slug=provider_slug,
                    status=WorkspacePaymentMethod.STATUS_ACTIVE,
                    is_deleted=False,
                )
            )
            if provider_slug == "stripe":
                if endpoint_name == "team_subscriptions":
                    methods = methods.filter(metadata__managed_subscription=True)
                    account_hint = None
                    secret_hint = None
                else:
                    account_hint = request.META.get("HTTP_STRIPE_ACCOUNT") or request.GET.get("account")
                    secret_hint = request.GET.get("secret")
                if account_hint:
                    methods = methods.filter(provider_account_id=account_hint)
                if secret_hint:
                    methods = methods.filter(webhooks__signing_secret=secret_hint)

            try:
                result = gateway.verify_webhook(request, endpoint_name, methods)
            except ValueError:
                continue

            # Scope guard (defense-in-depth against Connect/platform webhook
            # cross-delivery). A platform-scoped endpoint (``team_subscriptions``
            # / workspace billing) must NOT record or claim a CONNECT event —
            # one carrying a top-level ``account``. If it did, it would plant a
            # row in the shared PaymentEvent idempotency table (keyed by
            # ``event_id``), which makes the correct Connect/donations endpoint
            # dedupe-skip the same event and never book the donation. Connect
            # events belong to the donations path; ignore them here with no
            # side effects (no record, no claim) so the right handler can own
            # them. Legitimate platform events carry no ``account`` and are
            # unaffected. See docs/payments/LOCAL_STRIPE_WEBHOOKS.md.
            if force_platform_webhook and provider_slug == "stripe":
                event_account = self._extract_stripe_event_account(result.event)
                if event_account:
                    return LegacyWebhookVerificationResult(
                        event=result.event,
                        method=None,
                        workspace=None,
                        account_id=event_account,
                        legacy_context=result.legacy_context,
                        provider_slug=provider_slug,
                        api_key=result.api_key,
                        db_alias=None,
                        recordable=False,
                    )

            if provider_slug == "stripe" and not result.method and not force_platform_webhook:
                event_account = self._extract_stripe_event_account(result.event)
                if event_account:
                    # The authoritative account lives in the SIGNED body, so
                    # this resolution is only possible after verification —
                    # which is why the caller binds in two phases and does all
                    # of its writing in the second.
                    resolved_alias = resolve_db_alias_for_stripe_account(event_account)
                    if resolved_alias:
                        db_alias = resolved_alias
                        method = (
                            WorkspacePaymentMethod.objects.using(resolved_alias)
                            .select_related("workspace", "provider")
                            .filter(
                                provider__slug__startswith="stripe",
                                provider_account_id=event_account,
                                status=WorkspacePaymentMethod.STATUS_ACTIVE,
                                is_deleted=False,
                            )
                            .first()
                        )
                        if method:
                            result.method = method
                            result.workspace = method.workspace
                            result.account_id = method.provider_account_id or event_account

            return LegacyWebhookVerificationResult(
                event=result.event,
                method=result.method,
                workspace=result.workspace,
                account_id=result.account_id,
                legacy_context=result.legacy_context,
                provider_slug=provider_slug,
                api_key=result.api_key,
                db_alias=db_alias,
            )

        raise WebhookVerificationError("Unable to verify webhook payload.")
