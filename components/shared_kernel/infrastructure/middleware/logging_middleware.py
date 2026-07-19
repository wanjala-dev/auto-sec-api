"""Command bus middleware that logs dispatch timing and results.

Usage in the composition root::

    from components.shared_kernel.infrastructure.middleware.logging_middleware import (
        logging_middleware,
    )

    bus = InMemoryCommandBus()
    bus.add_middleware(logging_middleware)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from components.shared_kernel.application.commands import Command

logger = logging.getLogger("shared_kernel.command_bus")


def logging_middleware(command: Command, next_fn: Callable[[Command], Any]) -> Any:
    """Log command dispatch with timing information."""
    command_name = type(command).__name__
    logger.info("Dispatching %s (id=%s)", command_name, command.command_id)
    start = time.monotonic()
    try:
        result = next_fn(command)
        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "Completed %s (id=%s) in %.1fms",
            command_name,
            command.command_id,
            elapsed,
        )
        return result
    except Exception:
        elapsed = (time.monotonic() - start) * 1000
        logger.exception(
            "Failed %s (id=%s) after %.1fms",
            command_name,
            command.command_id,
            elapsed,
        )
        raise
