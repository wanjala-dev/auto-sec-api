from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from components.membership.application.use_cases.invitation_notification_use_case import (
    InvitationNotificationUseCase,
)


def test_team_invitation_notification_use_case_delegates_issued_flow():
    port = SimpleNamespace(notify_invitation_issued=Mock())
    use_case = InvitationNotificationUseCase(
        notification_port=port,
    )

    use_case.handle_invitation_issued(
        invitation="invitation",
        invited_user="user",
        actor_id="actor-1",
        request="request",
    )

    port.notify_invitation_issued.assert_called_once_with(
        invitation="invitation",
        invited_user="user",
        actor_id="actor-1",
        request="request",
        site_domain=None,
    )


def test_team_invitation_notification_use_case_delegates_accepted_flow():
    port = SimpleNamespace(notify_invitation_accepted=Mock())
    use_case = InvitationNotificationUseCase(
        notification_port=port,
    )

    use_case.handle_invitation_accepted(
        invitation="invitation",
        actor="actor",
    )

    port.notify_invitation_accepted.assert_called_once_with(
        invitation="invitation",
        actor="actor",
    )
