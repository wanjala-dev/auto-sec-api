"""The findings handler is bound to FindingObserved via @subscribes_to (Phase 3b).

Importing the handler module fires the decorator, so this is isolation-safe: it does
not depend on app-boot discovery order.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_finding_observed_handler_is_subscribed():
    from components.findings.application.handlers.finding_observed_handler import (
        handle_finding_observed,
    )
    from components.shared_kernel.application.subscription_registry import SubscriptionRegistry
    from components.shared_kernel.domain.events import FindingObserved

    assert (FindingObserved, handle_finding_observed) in SubscriptionRegistry.entries()
