"""Command bus middleware that wraps handler execution in a DB transaction.

Usage in the composition root::

    from components.shared_kernel.infrastructure.middleware.transaction_middleware import (
        transaction_middleware,
    )

    bus = InMemoryCommandBus()
    bus.add_middleware(transaction_middleware)
    # ... register handlers ...
"""

from __future__ import annotations

from typing import Any, Callable

from django.db import transaction

from components.shared_kernel.application.commands import Command


def transaction_middleware(command: Command, next_fn: Callable[[Command], Any]) -> Any:
    """Wrap the downstream handler in ``transaction.atomic()``."""
    with transaction.atomic():
        return next_fn(command)
