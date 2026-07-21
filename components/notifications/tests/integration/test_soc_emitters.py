"""SOC emitter coverage — findings, kill switch, and draft-PR HITL alerts
land in the notification funnel.

The bridge (``soc_notification_signal_bridge``) is registered by the
notifications app's ``ready()``; Celery is eager under test settings, so a
flushed ``transaction.on_commit`` produces the in-app Notification row
synchronously.
"""

from __future__ import annotations

import pytest

from infrastructure.persistence.notifications.models import Notification

pytestmark = pytest.mark.django_db


def _make_finding_task(workspace, team, *, source_type, title="Suspicious log burst"):
    from django.apps import apps as django_apps

    Task = django_apps.get_model("project", "Task")
    return Task.objects.create(
        workspace=workspace,
        team=team,
        title=title,
        created_by=team.created_by,
        source_type=source_type,
    )


class TestFindingFiledEmitter:
    def test_ai_finding_notifies_workspace_owner(
        self, workspace_factory, team_factory, django_capture_on_commit_callbacks
    ):
        workspace = workspace_factory()
        team = team_factory(workspace=workspace)

        with django_capture_on_commit_callbacks(execute=True):
            task = _make_finding_task(workspace, team, source_type="ai.log_watch")

        row = Notification.objects.get(recipient=workspace.workspace_owner)
        assert row.notification_type == Notification.NotificationType.AI_EVENT
        assert row.metadata["kind"] == "soc.finding_filed"
        assert row.metadata["source_type"] == "ai.log_watch"
        assert row.metadata["task_id"] == str(task.pk)
        assert row.metadata["link"] == f"/ai/v2/{workspace.pk}"
        assert "Suspicious log burst" in row.verb

    def test_sign_off_pending_gets_needs_human_wording(
        self, workspace_factory, team_factory, django_capture_on_commit_callbacks
    ):
        workspace = workspace_factory()
        team = team_factory(workspace=workspace)

        with django_capture_on_commit_callbacks(execute=True):
            _make_finding_task(workspace, team, source_type="ai.sign_off_pending", title="Weekly posture report")

        row = Notification.objects.get(recipient=workspace.workspace_owner)
        assert row.metadata["kind"] == "soc.sign_off_pending"
        assert "sign-off" in row.verb

    def test_human_task_does_not_notify(self, workspace_factory, team_factory, django_capture_on_commit_callbacks):
        workspace = workspace_factory()
        team = team_factory(workspace=workspace)

        with django_capture_on_commit_callbacks(execute=True):
            _make_finding_task(workspace, team, source_type="")

        assert Notification.objects.count() == 0

    def test_task_update_does_not_renotify(self, workspace_factory, team_factory, django_capture_on_commit_callbacks):
        workspace = workspace_factory()
        team = team_factory(workspace=workspace)
        with django_capture_on_commit_callbacks(execute=True):
            task = _make_finding_task(workspace, team, source_type="ai.log_watch")
        Notification.objects.all().delete()

        with django_capture_on_commit_callbacks(execute=True):
            task.status = task.DONE
            task.save(update_fields=["status"])

        assert Notification.objects.count() == 0


class TestKillSwitchEmitter:
    def test_kill_switch_trip_notifies_owner(self, workspace_factory, django_capture_on_commit_callbacks):
        workspace = workspace_factory()

        with django_capture_on_commit_callbacks(execute=True):
            workspace.ai_teammate_enabled = False
            workspace.save(update_fields=["ai_teammate_enabled"])

        row = Notification.objects.get(recipient=workspace.workspace_owner)
        assert row.notification_type == Notification.NotificationType.SYSTEM
        assert row.metadata["kind"] == "soc.ai_kill_switch"
        assert row.metadata["enabled"] is False
        assert "kill switch" in row.verb

    def test_unrelated_workspace_save_does_not_notify(self, workspace_factory, django_capture_on_commit_callbacks):
        workspace = workspace_factory()

        with django_capture_on_commit_callbacks(execute=True):
            workspace.workspace_name = "Renamed"
            workspace.save(update_fields=["workspace_name"])

        assert Notification.objects.count() == 0
