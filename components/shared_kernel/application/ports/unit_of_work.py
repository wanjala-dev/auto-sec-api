from __future__ import annotations

from typing import Callable, Protocol


class UnitOfWork(Protocol):
    """Coordinates transactional application work.

    Acts as a context manager — ``with uow_factory() as uow:`` opens the
    transactional scope and rolls back on exception. ``on_commit``
    schedules a callback to run after the surrounding transaction
    commits successfully (no-op if the transaction rolls back).
    """

    def __enter__(self) -> "UnitOfWork": ...

    def __exit__(self, exc_type, exc_val, exc_tb): ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def on_commit(self, callback: Callable[[], None]) -> None: ...
