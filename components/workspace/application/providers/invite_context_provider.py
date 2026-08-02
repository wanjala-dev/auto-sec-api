"""Provider/composition root for the invite-context read use case.

The team persona-invite CREATE flow resolves + authorizes its target through
``workspace`` (the owning context) via this provider. Lazy-imports the ORM
adapter so importing this module is free of infrastructure deps at load time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from components.workspace.application.use_cases.read_invite_context_use_case import (
        ReadInviteContextUseCase,
    )


class InviteContextProvider:
    """Driving-side façade for the invite-context read use case."""

    def build_use_case(self) -> ReadInviteContextUseCase:
        from components.workspace.application.use_cases.read_invite_context_use_case import (
            ReadInviteContextUseCase,
        )
        from components.workspace.infrastructure.repositories.invite_context_read_repository import (
            OrmInviteContextReadRepository,
        )

        return ReadInviteContextUseCase(store=OrmInviteContextReadRepository())


_default = InviteContextProvider()


def get_invite_context_provider() -> InviteContextProvider:
    """Return the default provider — composition root for the invite-context read
    use case. Override by monkeypatching ``_default`` in tests."""
    return _default
