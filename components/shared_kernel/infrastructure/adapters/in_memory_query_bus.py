"""In-process query bus implementation.

Routes ``Query`` instances to their registered ``QueryHandler``
using a simple dict registry.
"""

from __future__ import annotations

import logging
from typing import Any

from components.shared_kernel.application.handlers import QueryHandler
from components.shared_kernel.application.queries import Query
from components.shared_kernel.application.ports.query_bus import QueryBus

logger = logging.getLogger(__name__)


class InMemoryQueryBus(QueryBus):
    """Synchronous, in-process query bus."""

    def __init__(self) -> None:
        self._handlers: dict[type[Query], QueryHandler] = {}

    # ── Registration ─────────────────────────────────────────────────

    def register(self, query_type: type[Query], handler: QueryHandler) -> None:
        """Bind *query_type* → *handler*."""
        if query_type in self._handlers:
            logger.warning(
                "Overwriting handler for %s: %s → %s",
                query_type.__name__,
                type(self._handlers[query_type]).__name__,
                type(handler).__name__,
            )
        self._handlers[query_type] = handler

    # ── Dispatch ─────────────────────────────────────────────────────

    def ask(self, query: Query) -> Any:
        """Route *query* to its handler, or raise ``KeyError``."""
        handler = self._handlers.get(type(query))
        if handler is None:
            raise KeyError(
                f"No handler registered for {type(query).__name__}. "
                f"Registered: {[q.__name__ for q in self._handlers]}"
            )
        return handler.handle(query)
