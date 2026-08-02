"""Provider/composition root for the invite-driven membership write use case.

The team persona-invite accept flow delegates the ``WorkspaceMembership`` /
``WorkspaceRole`` / ``WorkspaceGroup*`` write into ``workspace`` (the owning
context) through this provider. Lazy-imports the ORM adapter so importing this
module is free of infrastructure deps at load time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — type-only import
    from components.workspace.application.use_cases.write_invite_membership_use_case import (
        WriteInviteMembershipUseCase,
    )


class InviteMembershipProvider:
    """Driving-side façade for the invite membership write use case."""

    def build_use_case(self) -> WriteInviteMembershipUseCase:
        from components.workspace.application.use_cases.write_invite_membership_use_case import (
            WriteInviteMembershipUseCase,
        )
        from components.workspace.infrastructure.repositories.invite_membership_repository import (
            OrmInviteMembershipRepository,
        )

        return WriteInviteMembershipUseCase(store=OrmInviteMembershipRepository())


_default = InviteMembershipProvider()


def get_invite_membership_provider() -> InviteMembershipProvider:
    """Return the default provider — composition root for the invite membership
    write use case. Override by monkeypatching ``_default`` in tests."""
    return _default
