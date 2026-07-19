"""Provider for ORM model classes living in ``infrastructure.persistence.users``.

Controllers in the ``identity``, ``membership``, ``payments`` and
``shared_platform`` bounded contexts need access to ``CustomUser`` and
``UserProfile`` (and other ``users`` models) but Explicit Architecture
forbids controllers importing infrastructure directly. This provider is
the single seam: it lazily imports each model class inside a property /
method body so the module is framework-free at import time, then hands
the class back to the caller so existing ``Model.objects.filter(...)``
call sites keep working unchanged.

Reference: ``components/identity/application/providers/magic_link_provider.py``
and ``components/budgeting/application/providers/bank_overview_repository_provider.py``.
"""

from __future__ import annotations

from typing import Any


class UsersModelsProvider:
    """Lazy facade over ORM classes in ``infrastructure.persistence.users``.

    Each property defers the ``from infrastructure.persistence.users...``
    import to call time so that importing this module is side-effect free
    and does not pull Django / ORM machinery into the application layer.
    """

    @property
    def CustomUser(self) -> Any:
        from infrastructure.persistence.users.models import CustomUser
        return CustomUser

    @property
    def UserProfile(self) -> Any:
        from infrastructure.persistence.users.models import UserProfile
        return UserProfile

    @property
    def ContributorProfile(self) -> Any:
        from infrastructure.persistence.users.models import ContributorProfile
        return ContributorProfile

    @property
    def MagicLinkToken(self) -> Any:
        from infrastructure.persistence.users.models import MagicLinkToken
        return MagicLinkToken

    @property
    def AuthAuditEvent(self) -> Any:
        from infrastructure.persistence.users.models import AuthAuditEvent
        return AuthAuditEvent

    @property
    def InvitedUser(self) -> Any:
        from infrastructure.persistence.users.models import InvitedUser
        return InvitedUser


_default = UsersModelsProvider()


def get_users_models_provider() -> UsersModelsProvider:
    """Return the default :class:`UsersModelsProvider` instance.

    Controllers call this once per view method and then read whichever
    model property they need — the actual ``infrastructure.persistence``
    import happens inside the property body, keeping the application
    layer framework-free at module load.
    """
    return _default
