"""Auto-discovery contract: every shipped handler is in the registry.

After Phase 3 (Action List P1 #14) the only durable record of which
detector events have a specialist handler is the registry itself —
``infrastructure/persistence/ai/apps.py`` no longer hard-codes the
subscriptions. This test locks in the contract.

When a new specialist agent ships (items 20-24), add it to the
``EXPECTED_SUBSCRIPTIONS`` set so future regressions get caught.
"""
from __future__ import annotations

import pytest

from components.agents.application.subscription_registry_service import (
    SubscriptionRegistry,
)


@pytest.fixture
def discovered_entries():
    """Run discovery once and yield the registry's entries.

    We deliberately do NOT ``clear()`` afterward — the registry's
    job is to be populated at boot and stay that way for the process
    lifetime. Clearing here would break later tests that rely on the
    publisher having the handlers attached. The autouse fixture in
    ``test_subscription_registry.py`` only runs within that test
    module's scope so the global registry survives.
    """
    SubscriptionRegistry.discover()
    return SubscriptionRegistry.entries()


# Map of "expected handler module:function name" → "event class name".
# Update when new specialists ship or existing handlers move.
EXPECTED_SUBSCRIPTIONS: set[tuple[str, str]] = {
    (
        "components.agents.application.handlers.budget_specialist_handler",
        "BookBalanceFindingsDetected",
    ),
    (
        "components.agents.application.handlers.budget_variance_specialist_handler",
        "BudgetVarianceFindingsDetected",
    ),
    (
        "components.agents.application.handlers.budget_anomaly_specialist_handler",
        "BudgetAnomalyFindingsDetected",
    ),
    (
        "components.agents.application.handlers.project_at_risk_specialist_handler",
        "ProjectAtRiskFindingsDetected",
    ),
    (
        "components.agents.application.handlers.sponsor_churn_specialist_handler",
        "SponsorChurnRiskFindingsDetected",
    ),
    (
        "components.agents.application.handlers.grant_deadline_specialist_handler",
        "GrantDeadlineUpcomingFindingsDetected",
    ),
    (
        "components.agents.application.handlers.finance_specialist_handler",
        "FinancialReportGenerated",
    ),
    (
        "components.agents.application.handlers.sponsorship_specialist_handler",
        "PaymentSucceeded",
    ),
    (
        "components.agents.application.handlers.project_specialist_handler",
        "ProjectCreated",
    ),
    (
        "components.agents.application.handlers.grants_specialist_handler",
        "OpportunityCreated",
    ),
    (
        "components.agents.application.handlers.transaction_specialist_handler",
        "TransactionCreated",
    ),
}


class TestAutoDiscovery:
    def test_every_expected_subscription_is_registered(
        self, discovered_entries
    ):
        observed = {
            (handler.__module__, event_type.__name__)
            for event_type, handler in discovered_entries
        }
        missing = EXPECTED_SUBSCRIPTIONS - observed
        assert missing == set(), (
            f"Expected subscriptions not found in the registry — has a "
            f"handler module lost its @subscribes_to decorator? "
            f"Missing: {missing}"
        )

    def test_registry_is_non_empty(self, discovered_entries):
        # Defence in depth: even if EXPECTED_SUBSCRIPTIONS goes empty
        # someday (e.g. all handlers extracted), the registry shouldn't
        # be silently empty after discovery.
        assert len(discovered_entries) > 0

    def test_handler_modules_actually_exist(self, discovered_entries):
        # Every registered handler should still be a callable in its
        # declared module (i.e. nothing was registered then deleted).
        import importlib

        for event_type, handler in discovered_entries:
            module = importlib.import_module(handler.__module__)
            assert getattr(module, handler.__name__, None) is handler
