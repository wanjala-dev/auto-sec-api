"""In-process command bus implementation with middleware support.

Routes ``Command`` instances to their registered ``CommandHandler``
using a simple dict registry.  Registration happens in the composition
root (provider) at startup.

Middleware callables are invoked in registration order *around* the
handler, forming a pipeline:  ``m1(m2(handler))``

For async / distributed commands, create a ``CeleryCommandBus`` or
``SQSCommandBus`` adapter that implements the same ``CommandBus`` port.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from components.shared_kernel.application.commands import Command
from components.shared_kernel.application.handlers import CommandHandler
from components.shared_kernel.application.ports.command_bus import CommandBus

logger = logging.getLogger(__name__)

# Middleware signature:  (command, next_fn) -> Any
# where next_fn: (Command) -> Any  is the next step in the pipeline.
Middleware = Callable[[Command, Callable[[Command], Any]], Any]


class InMemoryCommandBus(CommandBus):
    """Synchronous, in-process command bus with optional middleware."""

    def __init__(self) -> None:
        self._handlers: dict[type[Command], CommandHandler] = {}
        self._middleware: list[Middleware] = []

    # ── Registration ─────────────────────────────────────────────────

    def register(self, command_type: type[Command], handler: CommandHandler) -> None:
        """Bind *command_type* → *handler*.

        Called by the composition root during wiring.
        """
        if command_type in self._handlers:
            logger.warning(
                "Overwriting handler for %s: %s → %s",
                command_type.__name__,
                type(self._handlers[command_type]).__name__,
                type(handler).__name__,
            )
        self._handlers[command_type] = handler

    def add_middleware(self, middleware: Middleware) -> None:
        """Append *middleware* to the dispatch pipeline.

        Middleware is called in registration order, wrapping the innermost
        handler call.  Each middleware receives ``(command, next_fn)`` and
        must call ``next_fn(command)`` to continue the pipeline.
        """
        self._middleware.append(middleware)

    # ── Dispatch ─────────────────────────────────────────────────────

    def dispatch(self, command: Command) -> Any:
        """Route *command* through middleware, then to its handler."""
        handler = self._handlers.get(type(command))
        if handler is None:
            raise KeyError(
                f"No handler registered for {type(command).__name__}. "
                f"Registered: {[c.__name__ for c in self._handlers]}"
            )

        # Build the pipeline: innermost is the handler, wrapped by middleware
        def innermost(cmd: Command) -> Any:
            return handler.handle(cmd)

        pipeline = innermost
        for mw in reversed(self._middleware):
            prev = pipeline

            def make_step(m: Middleware, nxt: Callable) -> Callable:
                return lambda cmd: m(cmd, nxt)

            pipeline = make_step(mw, prev)

        return pipeline(command)
