"""Port (team-owned): issue JWT tokens for a freshly-accepted invitee.

The accept flow returns access/refresh tokens so the frontend can drop the
invitee straight into their dashboard. JWT issuance is a framework concern
(simplejwt), so it lives behind this port; the use case stays framework-free.

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class IssuedTokens:
    access: str
    refresh: str


class InviteTokenPort(abc.ABC):
    @abc.abstractmethod
    def issue_for_user(self, *, user_id: str) -> IssuedTokens:
        """Issue an access + refresh token pair for the accepted invitee."""
        ...
