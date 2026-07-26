"""Auto-discovery contract: every shipped handler is in the registry.

The only durable record of which domain events have a handler is the registry
itself — ``infrastructure/persistence/ai/apps.py`` no longer hard-codes the
subscriptions. This test locks in the contract for the agents handler package.

When a new handler ships in a discovered package, add it to
``EXPECTED_SUBSCRIPTIONS`` so future regressions (a lost ``@subscribes_to``) get
caught. (Trimmed 2026-07-25 to the real post-fork handlers — the nonprofit
specialist handlers referenced here previously were removed in the fork strip.)
"""

from __future__ import annotations

import pytest

from components.shared_kernel.application.subscription_registry import (
    SubscriptionRegistry,
)

# The handler packages the composition root (ai/apps.py) discovers today.
_AGENTS_HANDLERS = "components.agents.application.handlers"


@pytest.fixture
def discovered_entries():
    """Run discovery once and yield the registry's entries.

    We deliberately do NOT ``clear()`` afterward — the registry's job is to be
    populated at boot and stay that way for the process lifetime.
    """
    SubscriptionRegistry.discover((_AGENTS_HANDLERS,))
    return SubscriptionRegistry.entries()


# Map of "handler module" → "event class name" for the real, shipped handlers.
EXPECTED_SUBSCRIPTIONS: set[tuple[str, str]] = {
    (f"{_AGENTS_HANDLERS}.project_at_risk_specialist_handler", "ProjectAtRiskFindingsDetected"),
    (f"{_AGENTS_HANDLERS}.project_specialist_handler", "ProjectCreated"),
    (f"{_AGENTS_HANDLERS}.sign_off_feedback_handler", "SignOffDecisionRecorded"),
    (f"{_AGENTS_HANDLERS}.finding_raised_board_handler", "FindingRaised"),
}


class TestAutoDiscovery:
    def test_every_expected_subscription_is_registered(self, discovered_entries):
        observed = {(handler.__module__, event_type.__name__) for event_type, handler in discovered_entries}
        missing = EXPECTED_SUBSCRIPTIONS - observed
        assert missing == set(), (
            "Expected subscriptions not found in the registry — has a handler module "
            f"lost its @subscribes_to decorator? Missing: {missing}"
        )

    def test_registry_is_non_empty(self, discovered_entries):
        # Defence in depth: even if EXPECTED_SUBSCRIPTIONS goes empty someday, the
        # registry shouldn't be silently empty after discovery.
        assert len(discovered_entries) > 0

    def test_handler_modules_actually_exist(self, discovered_entries):
        # Every registered handler should still be a callable in its declared module.
        import importlib

        for _event_type, handler in discovered_entries:
            module = importlib.import_module(handler.__module__)
            assert getattr(module, handler.__name__, None) is handler
