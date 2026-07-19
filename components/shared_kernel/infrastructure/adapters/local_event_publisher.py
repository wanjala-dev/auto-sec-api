"""In-process event publisher implementation.

Routes ``DomainEvent`` instances to registered subscriber callables
using a simple dict registry.  Registration happens in the composition
root (provider) at startup.

For async / distributed events, create a ``CeleryEventPublisher`` or
``SQSEventPublisher`` adapter that implements the same ``EventPublisher``
port.

This adapter intentionally does **not** wrap subscriber calls in a
try/except — a failing subscriber should propagate.  Use-case-level
code can decide whether to catch subscriber errors or let them surface.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from components.shared_kernel.domain.events import DomainEvent
from components.shared_kernel.application.ports.event_publisher import EventPublisher

logger = logging.getLogger(__name__)

EventHandler = Callable[[DomainEvent], Any]


class LocalEventPublisher(EventPublisher):
    """Synchronous, in-process event publisher.

    Supports both:
    - **typed subscriptions**: handlers bound to a specific ``DomainEvent``
      subclass, invoked only for events of that exact type.
    - **global subscriptions**: handlers invoked for every published event
      (useful for logging, auditing, or bridging to Django signals).
    """

    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[EventHandler]] = {}
        self._global_handlers: list[EventHandler] = []

    # ── Registration ─────────────────────────────────────────────────

    def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: EventHandler,
    ) -> None:
        """Bind *handler* to *event_type*.

        Called by the composition root during wiring.
        """
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register *handler* to receive every published event."""
        self._global_handlers.append(handler)

    # ── Publishing ───────────────────────────────────────────────────

    def publish(self, event: DomainEvent) -> None:
        """Dispatch *event* to all matching subscribers synchronously."""
        event_type = type(event)
        handlers = self._handlers.get(event_type, [])
        all_handlers = [*handlers, *self._global_handlers]

        if not all_handlers:
            logger.debug(
                "No subscribers for %s (event_id=%s)",
                event_type.__name__,
                event.event_id,
            )
            return

        for handler in all_handlers:
            handler(event)

    # ── Introspection ────────────────────────────────────────────────

    @property
    def subscriber_count(self) -> int:
        """Total number of registered subscriptions (typed + global)."""
        typed = sum(len(hs) for hs in self._handlers.values())
        return typed + len(self._global_handlers)

    def clear(self) -> None:
        """Remove all subscriptions.  Useful for testing."""
        self._handlers.clear()
        self._global_handlers.clear()
