from __future__ import annotations

from typing import Any, Callable, Protocol

from components.shared_kernel.domain.events import DomainEvent


class EventPublisher(Protocol):
    """Publishes domain or application events after a successful use case.

    Implementations may dispatch synchronously (``LocalEventPublisher``),
    asynchronously via a task queue, or to an external message broker.
    """

    def publish(self, event: DomainEvent) -> None:
        """Publish a single event to all matching subscribers."""
        ...

    def subscribe(
        self,
        event_type: type[DomainEvent],
        handler: Callable[[DomainEvent], Any],
    ) -> None:
        """Register *handler* to receive events of *event_type*."""
        ...
