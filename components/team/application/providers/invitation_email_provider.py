"""Provider/composition root for team invitation email utilities.

Controllers (e.g. ``components/membership/api/controller.py``) consume
:class:`InvitationEmailProvider` instead of importing the concrete email
adapter directly. Keeps the API layer's import graph free of
infrastructure dependencies — the test
``test_controllers_do_not_import_concrete_adapters`` enforces this.

The provider lazy-imports the adapter symbols so module load is cheap
and tests can monkeypatch ``provider.send_persona_invitation`` without
dragging Django / template rendering into test discovery.
"""

from __future__ import annotations

from typing import Any


class InvitationEmailProvider:
    """Driving-side façade for the team invitation email adapter."""

    def send_persona_invitation(
        self,
        invitation: Any,
        *,
        inviter_user: Any = None,
        is_existing_user: bool = False,
    ) -> Any:
        """Send (or resend) a persona invitation email for ``invitation``.

        Thin wrapper that lazy-imports the concrete adapter so the
        application layer stays free of Django / template imports at
        module load time.
        """
        from components.team.infrastructure.adapters.utilities import (
            send_persona_invitation as _send_persona_invitation,
        )

        return _send_persona_invitation(
            invitation,
            inviter_user=inviter_user,
            is_existing_user=is_existing_user,
        )

    def send_invitation(
        self,
        to_email: str,
        code: str,
        team: Any,
        *,
        password_setup_url: str | None = None,
    ) -> Any:
        """Send a generic team invitation email."""
        from components.team.infrastructure.adapters.utilities import (
            send_invitation as _send_invitation,
        )

        return _send_invitation(
            to_email,
            code,
            team,
            password_setup_url=password_setup_url,
        )

    def send_invitation_accepted(self, team: Any, invitation: Any) -> Any:
        """Notify the inviter that ``invitation`` has been accepted."""
        from components.team.infrastructure.adapters.utilities import (
            send_invitation_accepted as _send_invitation_accepted,
        )

        return _send_invitation_accepted(team, invitation)

    def send_task_assignment_notification(
        self,
        request: Any,
        task: Any,
        user: Any,
        team: Any,
    ) -> Any:
        """Notify ``user`` that ``task`` has been assigned to them."""
        from components.team.infrastructure.adapters.utilities import (
            send_task_assignment_notification as _send_task_assignment_notification,
        )

        return _send_task_assignment_notification(request, task, user, team)


_default = InvitationEmailProvider()


def get_invitation_email_provider() -> InvitationEmailProvider:
    """Return the default provider — composition root for the team
    invitation email adapter. Override by monkeypatching this module's
    ``_default`` attribute in tests.
    """
    return _default
