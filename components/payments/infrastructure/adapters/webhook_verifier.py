from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from components.payments.application.providers import make_payment_gateway_provider
from components.payments.application.use_cases.record_and_claim_payment_event_use_case import (
    RecordAndClaimPaymentEventUseCase,
)
from components.payments.application.use_cases.verify_provider_webhook_use_case import (
    VerifiedProviderWebhookEnvelope,
    VerifyProviderWebhookUseCase,
)
from components.payments.domain.errors import WebhookVerificationError
from components.payments.infrastructure.adapters.payment_utils import resolve_db_alias_for_stripe_account
from components.payments.infrastructure.repositories.orm_payment_event_claim_repository import (
    OrmPaymentEventClaimRepository,
)
from components.payments.infrastructure.repositories.orm_payment_event_recording_repository import (
    OrmPaymentEventRecordingRepository,
)
from components.shared_platform.infrastructure.middleware.tenant_middlewares import set_db_for_router
from infrastructure.persistence.workspaces.models import Workspace
from infrastructure.persistence.workspaces.payments.models import PaymentEvent, WorkspacePaymentMethod


@dataclass(frozen=True)
class LegacyWebhookVerificationResult:
    event: Any
    method: WorkspacePaymentMethod | None
    workspace: Workspace | None
    account_id: str | None
    legacy_context: object | None
    provider_slug: str
    payment_event: PaymentEvent | None
    payment_event_duplicate: bool
    payment_event_processable: bool
    api_key: str | None


class LegacyIncomingWebhookVerifier:
    """Transitional verifier that keeps the old webhook contract while delegating into payments components."""

    @staticmethod
    def _extract_stripe_event_account(event: object) -> str | None:
        if isinstance(event, dict):
            return event.get("account")
        return getattr(event, "account", None)

    def verify(self, request, endpoint_name: str | None = None) -> LegacyWebhookVerificationResult:
        force_platform_webhook = endpoint_name == "team_subscriptions"
        account_id = request.META.get("HTTP_STRIPE_ACCOUNT") or request.GET.get("account")
        if account_id and not force_platform_webhook:
            db_alias = resolve_db_alias_for_stripe_account(account_id)
            if db_alias:
                set_db_for_router(db_alias)

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
                        payment_event=None,
                        payment_event_duplicate=False,
                        payment_event_processable=False,
                        api_key=result.api_key,
                    )

            if provider_slug == "stripe" and not result.method and not force_platform_webhook:
                event_account = self._extract_stripe_event_account(result.event)
                if event_account:
                    db_alias = resolve_db_alias_for_stripe_account(event_account)
                    if db_alias:
                        set_db_for_router(db_alias)
                        method = (
                            WorkspacePaymentMethod.objects.using(db_alias)
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

            handling = VerifyProviderWebhookUseCase(
                RecordAndClaimPaymentEventUseCase(
                    payment_event_recorder=OrmPaymentEventRecordingRepository(),
                    payment_event_claims=OrmPaymentEventClaimRepository(),
                )
            ).execute(
                envelope=VerifiedProviderWebhookEnvelope(
                    provider=provider_slug,
                    event=result.event,
                    account_id=result.account_id,
                    workspace_id=getattr(result.workspace, "id", None),
                    method_id=getattr(result.method, "id", None),
                ),
                claimed_by="components.payments.infrastructure.webhook_verifier",
                claim_message="Webhook received.",
            )
            payment_event = (
                PaymentEvent.objects.filter(id=handling.intake.payment_event_id).first()
                if handling.intake.payment_event_id
                else None
            )

            return LegacyWebhookVerificationResult(
                event=result.event,
                method=result.method,
                workspace=result.workspace,
                account_id=result.account_id,
                legacy_context=result.legacy_context,
                provider_slug=provider_slug,
                payment_event=payment_event,
                payment_event_duplicate=bool(payment_event and not handling.intake.is_new),
                payment_event_processable=bool(handling.intake.claimed) if payment_event else True,
                api_key=result.api_key,
            )

        raise WebhookVerificationError("Unable to verify webhook payload.")
