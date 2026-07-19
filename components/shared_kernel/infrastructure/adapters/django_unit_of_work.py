"""Django ORM-based Unit of Work adapter.

Wraps Django's ``transaction.atomic()`` to provide a UoW boundary.
Use this as a context manager or call ``commit`` / ``rollback`` explicitly.
"""

from __future__ import annotations

from django.db import transaction

from components.shared_kernel.application.ports.unit_of_work import UnitOfWork


class DjangoUnitOfWork(UnitOfWork):
    """Uses ``django.db.transaction`` as the transactional boundary."""

    def __init__(self, using: str = "default") -> None:
        self._using = using
        self._atomic: transaction.Atomic | None = None

    def __enter__(self) -> "DjangoUnitOfWork":
        self._atomic = transaction.atomic(using=self._using)
        self._atomic.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._atomic is not None:
            return self._atomic.__exit__(exc_type, exc_val, exc_tb)

    def commit(self) -> None:
        """No-op — Django auto-commits when the atomic block exits cleanly."""

    def rollback(self) -> None:
        """Force rollback by raising inside the atomic block."""
        if self._atomic is not None:
            transaction.set_rollback(True, using=self._using)

    def on_commit(self, callback) -> None:
        """Schedule ``callback`` to run after the surrounding transaction
        commits successfully. No-op if the transaction rolls back."""
        transaction.on_commit(callback, using=self._using)
