"""Model provider for ``infrastructure.persistence.workspaces.payments`` ORM classes.

Controllers must not import Django ORM models directly — the Explicit
Architecture rules forbid the API layer from depending on concrete
persistence implementations. Call sites obtain the model class via this
provider's lazy lookup instead.

**Why this provider exists (fork-drift, fixed 2026-08-18).** The SaaS payment
ledger (``PaymentProvider`` / ``WorkspacePaymentMethod`` / ``PaymentPlan`` /
``PaymentWebhookEndpoint`` / …) is *owned by the payments bounded context*, but
its tables are registered under the ``workspaces`` Django app — the module is
imported at the bottom of ``infrastructure/persistence/workspaces/models.py`` so
Django attributes the models to that app and keeps their migrations in
``workspaces/migrations/``. That physical placement misled the payments
controller into asking ``WorkspacesModelsProvider`` for these classes. That
provider only ever exposed the workspace root + membership/roles/workflow
models, so every read raised::

    AttributeError: 'WorkspacesModelsProvider' object has no attribute
                    'WorkspacePaymentMethod'

…and the entire payments read surface 500'd. Same fork-drift shape, and the
same fix, as ``Plan`` — see the module docstring of
``components/subscription/application/providers/subscription_models_provider.py``.

**The rule:** app registration is a persistence detail; *ownership* decides which
context's provider serves a model. Payment-ledger models are served here. Ask
the workspaces provider only for workspace-owned models (``Workspace``,
``WorkspaceMembership``, …).

Each property performs the ``from infrastructure.persistence...`` import inside
its body so module import time stays framework-free (stdlib + ``typing`` only at
the top).
"""

from __future__ import annotations

from typing import Any


class PaymentsModelsProvider:
    """Lazy accessors for the payment-ledger ORM models."""

    @property
    def PaymentProvider(self) -> Any:
        from infrastructure.persistence.workspaces.payments.models import (
            PaymentProvider,
        )

        return PaymentProvider

    @property
    def WorkspacePaymentMethod(self) -> Any:
        from infrastructure.persistence.workspaces.payments.models import (
            WorkspacePaymentMethod,
        )

        return WorkspacePaymentMethod

    @property
    def PaymentPlan(self) -> Any:
        from infrastructure.persistence.workspaces.payments.models import (
            PaymentPlan,
        )

        return PaymentPlan

    @property
    def PaymentWebhookEndpoint(self) -> Any:
        from infrastructure.persistence.workspaces.payments.models import (
            PaymentWebhookEndpoint,
        )

        return PaymentWebhookEndpoint


_default = PaymentsModelsProvider()


def get_payments_models_provider() -> PaymentsModelsProvider:
    """Return the default provider instance.

    Override by monkeypatching this module's ``_default`` attribute in
    tests.
    """
    return _default
