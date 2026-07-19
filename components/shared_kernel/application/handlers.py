"""Handler protocols for the Command/Query Bus.

Each use case implements one of these protocols.  The bus matches
``Command → CommandHandler`` and ``Query → QueryHandler`` at runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from components.shared_kernel.application.commands import Command
from components.shared_kernel.application.queries import Query

C = TypeVar("C", bound=Command)
Q = TypeVar("Q", bound=Query)


class CommandHandler(ABC, Generic[C]):
    """Handles a single ``Command`` type.

    Implementations live in ``application/use_cases/`` — they *are*
    the use cases.
    """

    @abstractmethod
    def handle(self, command: C) -> Any:
        """Execute the use case for *command*."""
        ...


class QueryHandler(ABC, Generic[Q]):
    """Handles a single ``Query`` type (CQRS read side).

    Implementations live in ``application/queries/`` and return DTOs.
    """

    @abstractmethod
    def handle(self, query: Q) -> Any:
        """Execute the query and return a DTO / read model."""
        ...
