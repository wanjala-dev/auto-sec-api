"""Port: schedule a callback to run after the surrounding transaction commits.

Application code calls ``on_commit_scheduler(callback)`` instead of
``django.db.transaction.on_commit(callback)`` so the application layer
stays framework-free. The concrete adapter
(``DjangoOnCommitScheduler``) is wired by the composition root.

If the surrounding code is not in a transaction, the Django adapter
runs ``callback`` immediately — matching Django's native behavior. A
test in-memory adapter typically runs immediately too.
"""

from __future__ import annotations

from typing import Callable, Protocol


class OnCommitScheduler(Protocol):
    def __call__(self, callback: Callable[[], None]) -> None: ...
