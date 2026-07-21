"""Integration coverage for the realtime notification leg (T1-S2).

Verifies the funnel end-to-end with a fake channel layer: dispatching a
notification publishes a ``notification.created`` envelope (serialized
row + fresh unread count) to the recipient's ``user.<id>.notifications``
group, and the REST mark-read endpoints publish read-state events. The
fake layer records ``group_send`` calls — the same seam channels-redis
implements in production.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from components.notifications.infrastructure.adapters.notification_service import (
    NotificationDispatcher,
)
from infrastructure.persistence.notifications.models import Notification
from infrastructure.realtime.groups import user_notifications_group

pytestmark = pytest.mark.django_db


class FakeChannelLayer:
    def __init__(self):
        self.sent: list[tuple[str, dict]] = []

    async def group_send(self, group, message):
        self.sent.append((group, message))


@pytest.fixture
def fake_layer():
    layer = FakeChannelLayer()
    with patch("channels.layers.get_channel_layer", return_value=layer):
        yield layer


def test_dispatch_publishes_created_envelope_to_recipient_group(
    user_factory, workspace_factory, fake_layer, django_capture_on_commit_callbacks
):
    actor = user_factory()
    recipient = user_factory()
    workspace = workspace_factory()

    with django_capture_on_commit_callbacks(execute=True):
        NotificationDispatcher().dispatch(
            actor=actor,
            workspace=workspace,
            verb="shared a resource with you",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[recipient],
            metadata={"kind": "resource_share"},
        )

    row = Notification.objects.get(recipient=recipient)
    groups = [group for group, _ in fake_layer.sent]
    assert user_notifications_group(str(recipient.pk)) in groups

    _, message = next((g, m) for g, m in fake_layer.sent if g == user_notifications_group(str(recipient.pk)))
    assert message["type"] == "notification.event"
    envelope = message["envelope"]
    assert envelope["event_name"] == "notification.created"
    assert envelope["notification_id"] == str(row.id)
    assert envelope["unread_count"] == 1
    assert envelope["notification"]["verb"] == "shared a resource with you"
    # The dispatch task enriches metadata with the resolved deep link
    # before row creation — the envelope carries it too. In the SOC fork
    # every workspace-scoped notification deep-links to the workspace HUD.
    assert envelope["notification"]["metadata"] == {
        "kind": "resource_share",
        "link": f"/ai/v2/{workspace.pk}",
    }
    assert envelope["workspace_id"] == str(workspace.id)


def test_mark_read_endpoint_publishes_read_event(
    api_client, user_factory, fake_layer, django_capture_on_commit_callbacks
):
    actor = user_factory()
    recipient = user_factory()
    with django_capture_on_commit_callbacks(execute=True):
        NotificationDispatcher().dispatch(
            actor=actor,
            workspace=None,
            verb="pinged you",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[recipient],
        )
    row = Notification.objects.get(recipient=recipient)
    fake_layer.sent.clear()

    api_client.force_authenticate(user=recipient)
    response = api_client.post(f"/notifications/{row.id}/mark_read/")
    assert response.status_code == 200

    group = user_notifications_group(str(recipient.pk))
    events = [m["envelope"]["event_name"] for g, m in fake_layer.sent if g == group]
    assert "notification.read" in events
    read_envelope = next(
        m["envelope"] for g, m in fake_layer.sent if g == group and m["envelope"]["event_name"] == "notification.read"
    )
    # The row flipped before publish — badge count must be fresh (0).
    assert read_envelope["unread_count"] == 0
    assert read_envelope["notification_id"] == str(row.id)


def test_mark_all_read_endpoint_publishes_all_read_event(
    api_client, user_factory, fake_layer, django_capture_on_commit_callbacks
):
    actor = user_factory()
    recipient = user_factory()
    with django_capture_on_commit_callbacks(execute=True):
        NotificationDispatcher().dispatch(
            actor=actor,
            workspace=None,
            verb="pinged you twice",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[recipient],
        )
    fake_layer.sent.clear()

    api_client.force_authenticate(user=recipient)
    response = api_client.post("/notifications/mark_all_read/")
    assert response.status_code == 200

    group = user_notifications_group(str(recipient.pk))
    events = [m["envelope"]["event_name"] for g, m in fake_layer.sent if g == group]
    assert "notification.all_read" in events


def test_disabled_flag_suppresses_publish(user_factory, fake_layer, settings, django_capture_on_commit_callbacks):
    settings.NOTIFICATIONS_REALTIME_ENABLED = False
    actor = user_factory()
    recipient = user_factory()

    with django_capture_on_commit_callbacks(execute=True):
        NotificationDispatcher().dispatch(
            actor=actor,
            workspace=None,
            verb="quiet ping",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[recipient],
        )

    # Row still created — only the realtime leg is off.
    assert Notification.objects.filter(recipient=recipient).exists()
    assert fake_layer.sent == []
