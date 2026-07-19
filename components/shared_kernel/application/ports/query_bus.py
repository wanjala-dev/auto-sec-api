"""Port for the application Query Bus (CQRS read side).

Controllers dispatch queries through this port.  The bus resolves the
correct handler at runtime based on ``query → handler`` registrations
wired in the composition root.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from components.shared_kernel.application.queries import Query


class QueryBus(ABC):
    """Dispatches a ``Query`` to its registered handler and returns the result."""

    @abstractmethod
    def ask(self, query: Query) -> Any:
        """Route *query* to the handler registered for its type."""
        ...
