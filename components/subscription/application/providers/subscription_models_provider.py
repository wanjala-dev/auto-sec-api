"""Model provider for ``infrastructure.persistence.subscription`` ORM classes.

Controllers must not import Django ORM models directly — the Explicit
Architecture rules forbid the API layer from depending on concrete
persistence implementations. Call sites obtain the model class via this
provider's lazy lookup instead.

``Plan`` (the platform's own SaaS tier — Free / Pro / Premium) is owned by
the **subscription** context. It used to live in the ``team`` app and was
relocated here, its canonical home, when the subscription context took
ownership of the tier catalogue; the physical table is still ``team_plan``
(a pure state move). Consumers that still ask the *team* models provider
for ``Plan`` are reading from the pre-move layout and will fail — ask here.

The property performs the ``from infrastructure.persistence...`` import
inside its body so module import time stays framework-free (stdlib +
``typing`` only at the top).

Note the division of labour with :mod:`plan_query_provider`: that provider
serves ``PlanQueryPort``, the DTO-shaped read seam other contexts use for
quota questions. This provider is the narrower ORM seam for the billing
path, which needs the live model (Stripe price ids, currency, interval)
and hands the row to the payment service.
"""

from __future__ import annotations

from typing import Any


class SubscriptionModelsProvider:
    """Lazy accessors for ``infrastructure.persistence.subscription`` models."""

    @property
    def Plan(self) -> Any:
        from infrastructure.persistence.subscription.models import Plan

        return Plan


_default = SubscriptionModelsProvider()


def get_subscription_models_provider() -> SubscriptionModelsProvider:
    """Return the default provider instance.

    Override by monkeypatching this module's ``_default`` attribute in
    tests.
    """
    return _default
