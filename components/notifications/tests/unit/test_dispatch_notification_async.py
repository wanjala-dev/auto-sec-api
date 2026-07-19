"""Verify the Celery dispatch task returns a JSON-serializable value.

Regression coverage for the 2026-05-27 demo bug — the task previously
returned the ORM ``Notification`` instance, which Celery couldn't
serialize into the Redis result backend. The encode error didn't
crash the report flow (the notification row was already created
inside the task body), but it suppressed the user-visible 'Report
ready' confirmation toast in the UI because the task was reported
as failed by Celery's eventing.

Rule violated: .claude/rules/celery-tasks.md — 'pass IDs, never
objects' (applies to return values too, not just kwargs).
"""

from __future__ import annotations

import json
from unittest.mock import patch
from uuid import uuid4

from components.notifications.workers.tasks import dispatch_notification_async


class _FakeUserManager:
    def __init__(self, users):
        self._users = {str(u.pk): u for u in users}

    def get(self, pk):
        try:
            return self._users[str(pk)]
        except KeyError as exc:
            from django.contrib.auth import get_user_model
            raise get_user_model().DoesNotExist from exc


class _FakeUser:
    def __init__(self, pk):
        self.pk = pk
        self.id = pk


class _FakeNotification:
    def __init__(self, notification_id):
        self.id = notification_id


def test_dispatch_notification_task_returns_json_serializable_payload():
    recipient = _FakeUser(uuid4())
    actor = _FakeUser(uuid4())
    notification_id = uuid4()

    with patch(
        "django.contrib.auth.get_user_model"
    ) as mock_get_user_model, patch(
        "components.notifications.infrastructure.adapters.utils.create_notification"
    ) as mock_create:
        mock_get_user_model.return_value.objects = _FakeUserManager(
            [recipient, actor]
        )
        mock_create.return_value = _FakeNotification(notification_id)

        result = dispatch_notification_async(
            recipient_id=str(recipient.pk),
            actor_id=str(actor.pk),
            verb="REPORT_GENERATED",
            notification_type="report",
        )

    # The returned payload must be JSON-encodable — Celery serializes
    # the task return value into Redis. ORM instance return = encode
    # error = lost result event.
    json.dumps(result)
    assert result == {"notification_id": str(notification_id)}


def test_dispatch_notification_task_returns_none_when_create_returns_none():
    """create_notification can decline (e.g. notification_type disabled
    for that recipient). Task should return None, which is trivially
    JSON-serializable."""
    recipient = _FakeUser(uuid4())
    actor = _FakeUser(uuid4())

    with patch(
        "django.contrib.auth.get_user_model"
    ) as mock_get_user_model, patch(
        "components.notifications.infrastructure.adapters.utils.create_notification"
    ) as mock_create:
        mock_get_user_model.return_value.objects = _FakeUserManager(
            [recipient, actor]
        )
        mock_create.return_value = None

        result = dispatch_notification_async(
            recipient_id=str(recipient.pk),
            actor_id=str(actor.pk),
            verb="REPORT_GENERATED",
            notification_type="report",
        )

    json.dumps(result)
    assert result is None
