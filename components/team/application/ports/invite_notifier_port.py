"""Port (team-owned): send the persona-invite email + in-app notification.

The magic-link email and the in-app "you were invited" notification are
infrastructure side-effects that read the ORM ``Invitation`` / inviter / recipient
rows. Keeping them behind this port lets the create-invite use case stay ORM- and
framework-free; the adapter re-fetches by id and performs the dispatch, swallowing
failures exactly as before (email is the primary channel).

No Django imports — depends only on the standard library.
"""

from __future__ import annotations

import abc


class InviteNotifierPort(abc.ABC):
    @abc.abstractmethod
    def send_invitation_email(
        self,
        *,
        invitation_id: str,
        inviter_user_id: str | None,
        is_existing_user: bool,
    ) -> None:
        """Send the magic-link email. Best-effort — never raises."""
        ...

    @abc.abstractmethod
    def notify_existing_user(
        self,
        *,
        invitation_id: str,
        inviter_user_id: str | None,
        recipient_user_id: str,
        token: str,
    ) -> None:
        """Fire the in-app invitation notification for an established user.
        Best-effort — never raises."""
        ...
