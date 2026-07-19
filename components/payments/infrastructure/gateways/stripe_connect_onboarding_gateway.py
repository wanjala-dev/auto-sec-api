from __future__ import annotations

from typing import Any

import stripe
from django.conf import settings

from components.payments.domain.errors import (
    PaymentOnboardingConfigurationError,
    PaymentOnboardingError,
)
from components.payments.domain.value_objects import (
    ConnectedPaymentAccount,
    PaymentOnboardingLink,
)
from components.payments.application.ports.payment_onboarding_port import PaymentOnboardingPort


def _account_field(account: Any, key: str, default=None):
    if hasattr(account, "get"):
        try:
            return account.get(key, default)
        except Exception:
            return getattr(account, key, default)
    return getattr(account, key, default)


class StripeConnectOnboardingGateway(PaymentOnboardingPort):
    """Stripe adapter for workspace payment-method onboarding."""

    def _configure(self) -> None:
        stripe.api_key = getattr(settings, "STRIPE_SECRET_KEY", None)
        if not stripe.api_key:
            raise PaymentOnboardingConfigurationError("STRIPE_SECRET_KEY is not configured.")

    def start_workspace_onboarding(
        self,
        *,
        existing_account_id: str | None,
        owner_email: str | None,
        return_url: str,
        refresh_url: str,
        display_name: str | None = None,
        workspace_id: str | None = None,
        method_id: str | None = None,
    ) -> PaymentOnboardingLink:
        self._configure()

        account_id = existing_account_id or ""
        created_account = False
        if not account_id:
            # Express accounts MUST request capabilities at create time —
            # without them Stripe's hosted onboarding flow has nothing to
            # provision, and the form can fail at submit-time with a
            # generic "Something went wrong". card_payments + transfers
            # are the standard pair for any Connect platform that takes
            # money on behalf of the connected account.
            #
            # ``country`` defaults to the platform's country if omitted.
            # Override here only if a workspace explicitly tells us a
            # different country (todo: surface this in the create UI).
            # Country MUST match the platform Stripe account's own country.
            # Mismatched combos (e.g. CA platform + US connected account)
            # require Stripe Cross-Border Payouts to be enabled — without
            # it, the Express onboarding form loads but fails at submit
            # with a vague "Something went wrong". Resolve by querying the
            # platform's own country at runtime; the env var override is
            # kept as an escape hatch for multi-platform deployments.
            default_country = getattr(
                settings, "STRIPE_CONNECT_DEFAULT_COUNTRY", ""
            )
            if not default_country:
                try:
                    platform_account = stripe.Account.retrieve()
                    default_country = (
                        _account_field(platform_account, "country", "") or "US"
                    )
                except stripe.error.StripeError:
                    default_country = "US"
            account_params: dict[str, Any] = {
                "type": "express",
                "country": default_country,
                "business_type": "non_profit",
                "capabilities": {
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
            }
            if owner_email:
                account_params["email"] = owner_email

            # Display name on Stripe Dashboard's connected-accounts list.
            # Without this every account shows up as the owner email and
            # ops can't tell them apart. Use the workspace/method name
            # plus a short suffix so re-onboarding the same workspace at
            # different times produces distinguishable rows.
            if display_name:
                account_params["business_profile"] = {
                    "name": display_name[:255],
                }

            # Machine-readable metadata for cross-system traceability.
            # workspace_id + method_id let ops jump from a Stripe Dashboard
            # row back to the WorkspacePaymentMethod that created it.
            metadata: dict[str, str] = {}
            if workspace_id:
                metadata["workspace_id"] = str(workspace_id)
            if method_id:
                metadata["method_id"] = str(method_id)
            if metadata:
                account_params["metadata"] = metadata

            try:
                account = stripe.Account.create(**account_params)
            except stripe.error.StripeError as exc:
                raise PaymentOnboardingError(
                    stage="account_creation",
                    details=str(exc),
                ) from exc
            account_id = str(_account_field(account, "id", ""))
            created_account = True

        try:
            account_link = stripe.AccountLink.create(
                account=account_id,
                type="account_onboarding",
                return_url=return_url,
                refresh_url=refresh_url,
            )
        except stripe.error.InvalidRequestError as exc:
            # The Connect account we cached was deleted on Stripe's side
            # (manual ops cleanup, account closure, etc.). Recover by
            # forgetting the dead id and creating a fresh account in this
            # same call so the user doesn't have to retry. Without this
            # recovery, every retry sees the same dead id and 502s.
            error_code = getattr(exc, "code", "") or ""
            if error_code != "resource_missing" or not existing_account_id:
                raise PaymentOnboardingError(
                    stage="link_creation",
                    details=str(exc),
                ) from exc

            account_params: dict[str, Any] = {
                "type": "express",
                "country": (
                    getattr(settings, "STRIPE_CONNECT_DEFAULT_COUNTRY", "")
                    or "US"
                ),
                "business_type": "non_profit",
                "capabilities": {
                    "card_payments": {"requested": True},
                    "transfers": {"requested": True},
                },
            }
            if owner_email:
                account_params["email"] = owner_email
            if display_name:
                account_params["business_profile"] = {
                    "name": display_name[:255],
                }
            rebuild_metadata: dict[str, str] = {}
            if workspace_id:
                rebuild_metadata["workspace_id"] = str(workspace_id)
            if method_id:
                rebuild_metadata["method_id"] = str(method_id)
            if rebuild_metadata:
                account_params["metadata"] = rebuild_metadata
            try:
                account = stripe.Account.create(**account_params)
            except stripe.error.StripeError as create_exc:
                raise PaymentOnboardingError(
                    stage="account_creation",
                    details=str(create_exc),
                ) from create_exc
            account_id = str(_account_field(account, "id", ""))
            created_account = True
            try:
                account_link = stripe.AccountLink.create(
                    account=account_id,
                    type="account_onboarding",
                    return_url=return_url,
                    refresh_url=refresh_url,
                )
            except stripe.error.StripeError as link_exc:
                raise PaymentOnboardingError(
                    stage="link_creation",
                    details=str(link_exc),
                ) from link_exc
        except stripe.error.StripeError as exc:
            raise PaymentOnboardingError(
                stage="link_creation",
                details=str(exc),
            ) from exc

        return PaymentOnboardingLink(
            account_id=account_id,
            redirect_url=str(_account_field(account_link, "url", "")),
            expires_at=_account_field(account_link, "expires_at"),
            created_account=created_account,
        )

    def fetch_connected_account(self, *, account_id: str) -> ConnectedPaymentAccount:
        self._configure()
        try:
            account = stripe.Account.retrieve(account_id)
        except stripe.error.StripeError as exc:
            raise PaymentOnboardingError(
                stage="account_retrieval",
                details=str(exc),
            ) from exc

        raw_default_currency = _account_field(account, "default_currency", None)
        normalized_default_currency: str | None = None
        if isinstance(raw_default_currency, str) and raw_default_currency.strip():
            normalized_default_currency = raw_default_currency.strip().upper()

        return ConnectedPaymentAccount(
            account_id=str(_account_field(account, "id", account_id)),
            details_submitted=bool(_account_field(account, "details_submitted", False)),
            charges_enabled=bool(_account_field(account, "charges_enabled", False)),
            payouts_enabled=bool(_account_field(account, "payouts_enabled", False)),
            capabilities=dict(_account_field(account, "capabilities", {}) or {}),
            requirements=dict(_account_field(account, "requirements", {}) or {}),
            default_currency=normalized_default_currency,
        )
