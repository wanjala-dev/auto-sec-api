"""Integration coverage for deep links riding the dispatcher funnel.

Asserts the delivery legs carry ``metadata["link"]`` in the SOC fork:

* the in-app ``Notification`` row (created by ``dispatch_notification_async``)
  carries the resolved workspace-HUD link,
* an explicit ``link=`` passed to ``dispatch()`` beats the resolver,
* a workspace-less dispatch writes no link.

Celery runs eagerly under test settings; ``django_capture_on_commit_callbacks``
flushes the ``transaction.on_commit`` hook the dispatcher enqueues through.
"""

from __future__ import annotations

import pytest

from components.notifications.infrastructure.adapters.notification_service import (
    NotificationDispatcher,
)
from infrastructure.persistence.notifications.models import Notification

pytestmark = pytest.mark.django_db


def _dispatch(django_capture_on_commit_callbacks, **kwargs):
    with django_capture_on_commit_callbacks(execute=True):
        NotificationDispatcher().dispatch(**kwargs)


class TestRowCarriesLink:
    def test_resolved_link_is_workspace_hud(self, user_factory, workspace_factory, django_capture_on_commit_callbacks):
        actor = user_factory()
        recipient = user_factory()
        workspace = workspace_factory()

        _dispatch(
            django_capture_on_commit_callbacks,
            actor=actor,
            workspace=workspace,
            verb="filed a new finding: exfiltration attempt",
            notification_type=Notification.NotificationType.AI_EVENT,
            recipients=[recipient],
            metadata={"kind": "soc.finding_filed"},
        )

        row = Notification.objects.get(recipient=recipient)
        assert row.metadata["link"] == f"/ai/v2/{workspace.pk}"

    def test_explicit_link_beats_resolver(self, user_factory, workspace_factory, django_capture_on_commit_callbacks):
        actor = user_factory()
        recipient = user_factory()
        workspace = workspace_factory()

        _dispatch(
            django_capture_on_commit_callbacks,
            actor=actor,
            workspace=workspace,
            verb="stopped the AI teammate (kill switch tripped)",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[recipient],
            link="/ai/v2/explicit-destination",
        )

        row = Notification.objects.get(recipient=recipient)
        assert row.metadata["link"] == "/ai/v2/explicit-destination"

    def test_workspace_less_dispatch_writes_no_link(self, user_factory, django_capture_on_commit_callbacks):
        actor = user_factory()
        recipient = user_factory()

        _dispatch(
            django_capture_on_commit_callbacks,
            actor=actor,
            workspace=None,
            verb="sent you a message",
            notification_type=Notification.NotificationType.MESSAGE,
            recipients=[recipient],
        )

        row = Notification.objects.get(recipient=recipient)
        assert "link" not in row.metadata
