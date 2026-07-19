"""Declarative subscription registry for specialist handlers.

Closes Action List item P1 #14 — the missing piece that blocks items
20-24 (the 5 specialist agents). Before this module, every new
specialist required hand-edits to ``infrastructure/persistence/ai/apps.py``
to wire its event subscription. That central-file coupling is what the
agents-as-teammates plan §Phase 3 calls out as the next-blocker.

Public API:

* ``@subscribes_to(EventClass)`` — decorator that registers a handler
  function for a given domain event type. May be stacked for handlers
  that react to multiple events.
* ``SubscriptionRegistry.bind_all(publisher)`` — called once at
  Django app ready(). Triggers auto-discovery of every handler module
  in ``components.agents.application.handlers``, then registers each
  ``(event_type, handler)`` pair with the publisher.
* ``SubscriptionRegistry.entries`` — read-only view of every
  registered subscription; useful for tests + introspection.

Auto-discovery walks ``components/agents/application/handlers/*.py``
(skipping modules whose names start with ``_``, matching the agent
auto-discovery pattern in ``components/agents/infrastructure/adapters/
langchain/agents/__init__.py``). Importing each handler module is what
fires the decorator and populates the registry.

Idempotency: ``bind_all`` is safe to call once. Calling it again would
re-register with the publisher; that's the publisher's concern — for
tests, call ``CeleryEventPublisher().clear()`` first.

Why not class-based specialists? The existing handlers are plain
functions: ``handle_X(event) -> None``. Keeping the decorator API
function-level matches that shape and avoids a forced refactor of
seven working handlers in this PR. A future PR can add a class-based
``@register_specialist`` shorthand on top if specialists grow shared
state.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any, Callable

from components.shared_kernel.domain.events import DomainEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[DomainEvent], Any]


class SubscriptionRegistry:
    """Module-level registry of ``(event_type, handler)`` subscriptions.

    Populated at handler-module import time via ``@subscribes_to(...)``
    and bound to the event publisher at Django app ready().
    """

    _entries: list[tuple[type[DomainEvent], EventHandler]] = []
    _discovered: bool = False

    @classmethod
    def register(
        cls,
        event_type: type[DomainEvent],
        handler: EventHandler,
    ) -> None:
        """Add a ``(event_type, handler)`` subscription.

        Called by ``@subscribes_to``; not normally called directly. Duplicates
        (same event type, same handler identity) are deduplicated — Python
        imports are cached so the decorator typically fires once per
        handler, but this guards against test paths that re-import.
        """
        entry = (event_type, handler)
        if entry in cls._entries:
            return
        cls._entries.append(entry)

    @classmethod
    def discover(cls) -> None:
        """Import every handler module under ``components.agents.application.handlers``.

        Importing fires ``@subscribes_to`` which populates the registry.
        Idempotent — the second call is a no-op via ``_discovered``.

        Modules whose names start with ``_`` are skipped (mirrors the
        agent auto-discovery pattern; underscore-prefixed modules are
        shared helpers, not handler entry points).
        """
        if cls._discovered:
            return
        cls._discovered = True

        import components.agents.application.handlers as handlers_pkg

        for _finder, name, _is_pkg in pkgutil.iter_modules(
            handlers_pkg.__path__
        ):
            if name.startswith("_"):
                continue
            module_path = f"{handlers_pkg.__name__}.{name}"
            try:
                importlib.import_module(module_path)
            except Exception:
                # One broken handler shouldn't void the whole agent boot —
                # log loudly and continue. The boot error path then surfaces
                # via test_subscription_registry_discovery.
                logger.exception(
                    "subscription_registry_handler_import_failed module=%s",
                    module_path,
                )

    @classmethod
    def bind_all(cls, publisher) -> None:
        """Register every collected subscription with the event publisher.

        Called once from ``infrastructure/persistence/ai/apps.py.ready()``.
        ``publisher`` is duck-typed — anything with a
        ``subscribe(event_type, handler)`` method works (production:
        ``CeleryEventPublisher``; tests: a stub).
        """
        cls.discover()
        for event_type, handler in cls._entries:
            publisher.subscribe(event_type, handler)
            logger.info(
                "subscription_registry_bound event=%s handler=%s",
                event_type.__name__,
                getattr(handler, "__qualname__", handler),
            )

    # ── Introspection / test helpers ─────────────────────────────────

    @classmethod
    def entries(cls) -> list[tuple[type[DomainEvent], EventHandler]]:
        """Read-only view of every registered subscription.

        Returns a shallow copy so callers can't mutate the registry by
        accident. Useful for tests that want to assert "the budget
        anomaly handler is registered for BudgetAnomalyFindingsDetected".
        """
        return list(cls._entries)

    @classmethod
    def clear(cls) -> None:
        """Drop every registered subscription. Test-only.

        Production code MUST NOT call this — it would silently break
        every detector → specialist path until the next process boot.
        Test code that needs a clean slate may call this in a fixture.
        """
        cls._entries.clear()
        cls._discovered = False


def subscribes_to(event_type: type[DomainEvent]):
    """Decorate an event-handler function with the domain event it consumes.

    Usage::

        @subscribes_to(BookBalanceFindingsDetected)
        def handle_book_balance_findings_detected(event) -> None:
            ...

    May be stacked for handlers that react to multiple events::

        @subscribes_to(BudgetVarianceFindingsDetected)
        @subscribes_to(BudgetAnomalyFindingsDetected)
        def handle_any_budget_finding(event) -> None:
            ...

    The function itself is returned unchanged — the decorator's only
    side effect is registering the subscription. Functions stay
    callable as plain ``handler(event)`` for tests and ad-hoc use.
    """

    def decorator(handler: EventHandler) -> EventHandler:
        SubscriptionRegistry.register(event_type, handler)
        return handler

    return decorator
