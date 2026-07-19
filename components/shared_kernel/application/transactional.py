"""Framework-free transactional primitives for the application layer.

Use cases that need a transaction boundary or a post-commit hook go
through this module instead of importing ``django.db.transaction``.
The concrete adapters live in ``shared_kernel.infrastructure.adapters``
and are lazy-imported inside each function body — so this module is
free of any Django imports at static-analysis time.

Usage::

    from components.shared_kernel.application.transactional import atomic, on_commit

    with atomic():
        # ... mutations
        on_commit(lambda: dispatch_followup.delay(...))
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator


@contextmanager
def atomic(using: str | None = None) -> Iterator[None]:
    """Open a transactional scope. Rolls back on exception.

    Pass ``using`` when the block contains a ``select_for_update`` (or any
    row lock) on a tenant-routed model. Under the multi-DB ``TenantRouter``
    a bare ``transaction.atomic()`` only opens a transaction on ``default``,
    so a lock issued against another alias raises
    ``TransactionManagementError: select_for_update cannot be used outside
    of a transaction``. Resolve the alias with :func:`db_alias_for` and
    thread it through both this scope and the locking query's ``.using()``.
    """
    from components.shared_kernel.infrastructure.adapters.django_unit_of_work import (
        DjangoUnitOfWork,
    )

    with DjangoUnitOfWork(using or "default"):
        yield


def db_alias_for(model) -> str:
    """Return the write DB alias for ``model`` under the tenant router.

    Framework-free: the actual ``django.db.router`` call lives in an
    infrastructure adapter, lazy-imported here so the application layer
    stays import-clean at static-analysis time.
    """
    from components.shared_kernel.infrastructure.adapters.django_db_routing import (
        db_alias_for_write,
    )

    return db_alias_for_write(model)


def on_commit(callback: Callable[[], None]) -> None:
    """Schedule ``callback`` to run after the surrounding transaction commits.

    If no transaction is active, the callback runs immediately
    (matching Django's native behaviour).
    """
    from components.shared_kernel.infrastructure.adapters.django_on_commit_scheduler import (
        django_on_commit_scheduler,
    )

    django_on_commit_scheduler(callback)
