"""Port for the application Command Bus.

Driving adapters (controllers, CLI, tasks) dispatch commands through this
port.  The bus resolves the correct handler at runtime based on
``command → handler`` registrations wired in the composition root.

Graca's Explicit Architecture / CQRS: *"The controller constructs a
Command and passes it to the relevant Bus."*
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from components.shared_kernel.application.commands import Command

T = TypeVar("T")


class CommandBus(ABC):
    """Dispatches a ``Command`` to its registered handler and returns the result."""

    @abstractmethod
    def dispatch(self, command: Command) -> Any:
        """Route *command* to the handler registered for its type."""
        ...
