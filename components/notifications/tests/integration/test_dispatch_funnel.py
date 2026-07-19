"""End-to-end coverage for the consolidated dispatcher funnel (T1-S1).

Covers the three behaviors the pipeline-consolidation slice added:

* ``allow_self_notify`` — system-generated events where the recipient stands
  in as actor (workflow runs, reports, security alerts, imports) must survive
  the funnel instead of silently vanishing.
* ``target_ref`` — the GenericFK target now crosses the Celery boundary as an
  ``[app_label, model_name, pk]`` triple; before this, dispatch() dropped the
  target on the async path.
* preference filtering applies to every migrated call site — a recipient with
  the master toggle off receives nothing.

Celery runs eagerly under the test settings; ``django_capture_on_commit_callbacks``
flushes the ``transaction.on_commit`` hook the dispatcher enqueues through.
"""

from __future__ import annotations

import pytest

from components.notifications.infrastructure.adapters.notification_service import (
    NotificationDispatcher,
    invalidate_preference_cache,
)
from components.notifications.infrastructure.adapters.utils import create_notification
from infrastructure.persistence.notifications.models import Notification

pytestmark = pytest.mark.django_db


def _dispatch(django_capture_on_commit_callbacks, **kwargs):
    with django_capture_on_commit_callbacks(execute=True):
        NotificationDispatcher().dispatch(**kwargs)


class TestAllowSelfNotify:
    def test_self_notification_dropped_by_default(self, user_factory, django_capture_on_commit_callbacks):
        user = user_factory()
        _dispatch(
            django_capture_on_commit_callbacks,
            actor=user,
            workspace=None,
            verb="liked your post",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[user],
        )
        assert not Notification.objects.filter(recipient=user).exists()

    def test_self_notification_created_when_allowed(self, user_factory, django_capture_on_commit_callbacks):
        user = user_factory()
        _dispatch(
            django_capture_on_commit_callbacks,
            actor=user,
            workspace=None,
            verb="Workflow “Welcome sequence” completed a run",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[user],
            allow_self_notify=True,
        )
        row = Notification.objects.get(recipient=user)
        assert row.actor_id == user.pk

    def test_create_notification_util_honors_allow_self_notify(self, user_factory):
        user = user_factory()
        assert (
            create_notification(
                recipient=user,
                actor=user,
                verb="self event",
                notification_type=Notification.NotificationType.SYSTEM,
            )
            is None
        )
        row = create_notification(
            recipient=user,
            actor=user,
            verb="self event",
            notification_type=Notification.NotificationType.SYSTEM,
            allow_self_notify=True,
        )
        assert row is not None


class TestTargetCrossesAsyncBoundary:
    def test_target_rehydrated_from_target_ref(
        self, user_factory, workspace_factory, django_capture_on_commit_callbacks
    ):
        actor = user_factory()
        recipient = user_factory()
        workspace = workspace_factory()

        _dispatch(
            django_capture_on_commit_callbacks,
            actor=actor,
            workspace=workspace,
            verb="invited you to join",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[recipient],
            # Any persisted model works as a GenericFK target; the workspace
            # row stands in for invitation/report/dispatch targets.
            target=workspace,
        )

        row = Notification.objects.get(recipient=recipient)
        assert row.content_object == workspace
        assert row.object_id == str(workspace.pk)


class TestPreferenceFilteringAppliesToFunnel:
    def test_master_toggle_off_suppresses_dispatch(self, user_factory, django_capture_on_commit_callbacks):
        from infrastructure.persistence.notifications.userpreferences.models import (
            UserPreference,
        )

        actor = user_factory()
        recipient = user_factory()
        UserPreference.objects.update_or_create(user=recipient, defaults={"notifications_enabled": False})
        # Signals on user creation can dispatch (and cache) an allow decision
        # before the toggle flips — mirror the preference endpoint, which
        # invalidates the decision cache on every change.
        invalidate_preference_cache(recipient.pk)

        _dispatch(
            django_capture_on_commit_callbacks,
            actor=actor,
            workspace=None,
            verb="shared a resource with you",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[recipient],
        )
        assert not Notification.objects.filter(recipient=recipient).exists()

    def test_master_toggle_off_suppresses_self_notify_dispatch(self, user_factory, django_capture_on_commit_callbacks):
        """allow_self_notify raises the self-drop, NOT the preference gate."""
        from infrastructure.persistence.notifications.userpreferences.models import (
            UserPreference,
        )

        user = user_factory()
        UserPreference.objects.update_or_create(user=user, defaults={"notifications_enabled": False})
        invalidate_preference_cache(user.pk)

        _dispatch(
            django_capture_on_commit_callbacks,
            actor=user,
            workspace=None,
            verb="Workflow run failed",
            notification_type=Notification.NotificationType.SYSTEM,
            recipients=[user],
            allow_self_notify=True,
        )
        assert not Notification.objects.filter(recipient=user).exists()
