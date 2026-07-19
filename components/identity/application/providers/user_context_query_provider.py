"""Provider for the user-context query repository.

External controllers (e.g. payments) read user context via this
provider instead of importing the concrete identity ORM repository.
"""

from __future__ import annotations

from typing import Any


class UserContextQueryProvider:
    def repository(self) -> Any:
        from components.identity.infrastructure.repositories.orm_user_context_query_repository import (
            OrmUserContextQueryRepository,
        )

        return OrmUserContextQueryRepository()


_default = UserContextQueryProvider()


def get_user_context_query_provider() -> UserContextQueryProvider:
    return _default
