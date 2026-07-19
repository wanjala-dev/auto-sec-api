"""Integration tests for the Phase 2 nonprofit action executors.

Covers the leaves added/fixed in this slice:
- ``add_tag`` / ``remove_tag`` mutate the directory contact's membership tags,
- ``update_field`` writes an allow-listed profile field and REJECTS others,
- ``message`` (email) calls the real platform email port (only the external
  email boundary is stubbed — never the workflow code itself),
- ``message`` (in_app) writes a real Notification row,
- each executor RAISES ``WorkflowActionError`` on genuine failure (fail loudly).

These enter through ``execute_node_action`` (the dispatch the engine calls), not
through private helpers — same principle as the engine suite.
"""

from __future__ import annotations

import pytest

from components.workflow.domain.errors import WorkflowActionError
from components.workflow.infrastructure.adapters import node_actions
from components.workflow.infrastructure.adapters.node_actions import execute_node_action
from infrastructure.persistence.notifications.models import Notification
from infrastructure.persistence.users.models import UserProfile
from infrastructure.persistence.workspaces.models import Tag, WorkspaceMembership
from infrastructure.persistence.workspaces.workflows.models import Workflow, WorkflowRun

pytestmark = pytest.mark.django_db


# --- builders --------------------------------------------------------------
def _workflow(workspace):
    return Workflow.objects.create(
        workspace=workspace,
        name="Phase2 flow",
        goal="campaign",
        status=Workflow.Status.PUBLISHED,
        version=1,
        graph={"nodes": [], "edges": []},
    )


def _run(workflow, target_user, target_type="contact"):
    return WorkflowRun.objects.create(
        workflow=workflow,
        workflow_version=1,
        status=WorkflowRun.Status.RUNNING,
        trigger_type="contact_added",
        trigger_payload={"target_id": str(target_user.id)},
        target_type=target_type,
        target_id=str(target_user.id),
    )


def _membership(workspace, user):
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=WorkspaceMembership.Role.MEMBER)


def _node(node_type, config):
    return {"id": node_type, "type": node_type, "label": node_type, "config": config}


# --- add_tag / remove_tag --------------------------------------------------
class TestTagActions:
    def test_add_tag_adds_to_membership(self, workspace_factory, user_factory):
        ws = workspace_factory()
        contact = user_factory()
        membership = _membership(ws, contact)
        run = _run(_workflow(ws), contact)

        out = execute_node_action(run, _node("add_tag", {"tag": "Lapsed Donor"}), {"tag": "Lapsed Donor"})

        assert out["status"] == "tagged"
        assert membership.tags.filter(name="Lapsed Donor").exists()

    def test_remove_tag_removes_from_membership(self, workspace_factory, user_factory):
        ws = workspace_factory()
        contact = user_factory()
        membership = _membership(ws, contact)
        tag = Tag.objects.create(name="Lapsed Donor")
        membership.tags.add(tag)
        run = _run(_workflow(ws), contact)

        out = execute_node_action(run, _node("remove_tag", {"tag": "Lapsed Donor"}), {"tag": "Lapsed Donor"})

        assert out["status"] == "untagged"
        assert not membership.tags.filter(name="Lapsed Donor").exists()

    def test_add_tag_no_membership_is_skipped_not_failed(self, workspace_factory, user_factory):
        ws = workspace_factory()
        contact = user_factory()  # NO membership created
        run = _run(_workflow(ws), contact)

        out = execute_node_action(run, _node("add_tag", {"tag": "X"}), {"tag": "X"})

        assert out["status"] == "skipped"

    def test_add_tag_no_tag_name_is_skipped(self, workspace_factory, user_factory):
        ws = workspace_factory()
        contact = user_factory()
        _membership(ws, contact)
        run = _run(_workflow(ws), contact)

        out = execute_node_action(run, _node("add_tag", {}), {})

        assert out["status"] == "skipped"

    def test_add_tag_raises_loudly_on_db_error(self, workspace_factory, user_factory, monkeypatch):
        ws = workspace_factory()
        contact = user_factory()
        _membership(ws, contact)
        run = _run(_workflow(ws), contact)

        def _boom(name):
            raise RuntimeError("db down")

        monkeypatch.setattr(node_actions, "_get_or_create_tag", _boom)

        with pytest.raises(WorkflowActionError):
            execute_node_action(run, _node("add_tag", {"tag": "X"}), {"tag": "X"})


# --- update_field ----------------------------------------------------------
class TestUpdateField:
    def test_updates_allow_listed_field(self, workspace_factory, user_factory):
        ws = workspace_factory()
        contact = user_factory()
        run = _run(_workflow(ws), contact)

        out = execute_node_action(
            run,
            _node("update_field", {"field": "title", "value": "Major Donor"}),
            {"field": "title", "value": "Major Donor"},
        )

        assert out["status"] == "updated"
        assert UserProfile.objects.get(user=contact).title == "Major Donor"

    def test_rejects_non_allow_listed_field(self, workspace_factory, user_factory):
        ws = workspace_factory()
        contact = user_factory()
        _membership(ws, contact)
        run = _run(_workflow(ws), contact)

        # ``is_staff`` is sensitive — must fail loudly, not silently skip/write.
        with pytest.raises(WorkflowActionError):
            execute_node_action(
                run,
                _node("update_field", {"field": "is_staff", "value": True}),
                {"field": "is_staff", "value": True},
            )

        contact.refresh_from_db()
        assert contact.is_staff is False

    def test_no_field_configured_is_skipped(self, workspace_factory, user_factory):
        ws = workspace_factory()
        contact = user_factory()
        run = _run(_workflow(ws), contact)

        out = execute_node_action(run, _node("update_field", {}), {})

        assert out["status"] == "skipped"


# --- message (email) -------------------------------------------------------
class _CapturingEmailAdapter:
    """Test double for the EmailSendingPort boundary (the only stub allowed)."""

    def __init__(self, *, result=True):
        self.result = result
        self.sent = []

    def send(self, message):
        self.sent.append(message)
        return self.result

    def send_templated(self, **kwargs):  # pragma: no cover - unused here
        return self.result


class _CapturingProvider:
    def __init__(self, adapter):
        self._adapter = adapter

    def adapter(self):
        return self._adapter


class TestMessageEmail:
    def _patch_email(self, monkeypatch, adapter):
        from components.shared_platform.application.providers import email_adapter_provider

        monkeypatch.setattr(
            email_adapter_provider,
            "get_email_adapter_provider",
            lambda: _CapturingProvider(adapter),
        )

    def test_email_calls_real_send_path(self, workspace_factory, user_factory, monkeypatch):
        adapter = _CapturingEmailAdapter()
        self._patch_email(monkeypatch, adapter)

        ws = workspace_factory()
        contact = user_factory(email="donor@example.com")
        run = _run(_workflow(ws), contact)
        config = {"channel": "email", "subject": "Thanks", "body": "Hi there"}

        out = execute_node_action(run, _node("message", config), config)

        assert out["status"] == "sent"
        assert len(adapter.sent) == 1
        assert adapter.sent[0].to == ["donor@example.com"]
        assert adapter.sent[0].subject == "Thanks"

    def test_email_no_recipient_is_skipped(self, workspace_factory, user_factory, monkeypatch):
        adapter = _CapturingEmailAdapter()
        self._patch_email(monkeypatch, adapter)

        ws = workspace_factory()
        contact = user_factory(email="")  # no deliverable address
        run = _run(_workflow(ws), contact)
        config = {"channel": "email", "subject": "Thanks", "body": "Hi"}

        out = execute_node_action(run, _node("message", config), config)

        assert out["status"] == "skipped"
        assert adapter.sent == []

    def test_email_send_failure_raises_loudly(self, workspace_factory, user_factory, monkeypatch):
        adapter = _CapturingEmailAdapter(result=False)  # backend reports failure
        self._patch_email(monkeypatch, adapter)

        ws = workspace_factory()
        contact = user_factory(email="donor@example.com")
        run = _run(_workflow(ws), contact)
        config = {"channel": "email", "subject": "Thanks", "body": "Hi"}

        with pytest.raises(WorkflowActionError):
            execute_node_action(run, _node("message", config), config)


# --- message (in_app) ------------------------------------------------------
class TestMessageInApp:
    def test_in_app_creates_notification(self, workspace_factory, user_factory, django_capture_on_commit_callbacks):
        ws = workspace_factory()
        contact = user_factory()
        run = _run(_workflow(ws), contact)
        config = {"channel": "in_app", "body": "Welcome to the program"}

        # In-app delivery flows through the dispatcher funnel (post-commit
        # enqueue) — flush on_commit callbacks so eager Celery runs.
        with django_capture_on_commit_callbacks(execute=True):
            out = execute_node_action(run, _node("message", config), config)

        assert out["status"] == "sent"
        note = Notification.objects.get(recipient=contact, workspace=ws)
        assert note.verb == "Welcome to the program"
        assert note.notification_type == Notification.NotificationType.SYSTEM


# --- anonymous donor (donation form / public gift): target_id is an EMAIL ---
class TestAnonymousDonorTarget:
    def _anon_run(self, workspace):
        # Form/public donors have no user row; the run targets them by email.
        return WorkflowRun.objects.create(
            workflow=_workflow(workspace),
            workflow_version=1,
            status=WorkflowRun.Status.RUNNING,
            trigger_type="form_completed",
            trigger_payload={
                "target_id": "anon.donor@example.com",
                "donor_email": "anon.donor@example.com",
                "amount": "25.00",
            },
            target_type="contact",
            target_id="anon.donor@example.com",
        )

    def test_email_falls_back_to_donor_email(self, workspace_factory, monkeypatch):
        adapter = _CapturingEmailAdapter()
        from components.shared_platform.application.providers import email_adapter_provider

        monkeypatch.setattr(
            email_adapter_provider,
            "get_email_adapter_provider",
            lambda: _CapturingProvider(adapter),
        )
        run = self._anon_run(workspace_factory())
        config = {"channel": "email", "subject": "Thank you", "body": "Thanks!"}

        out = execute_node_action(run, _node("message", config), config)

        # Emails the anonymous donor using the trigger payload's donor_email —
        # no crash on the non-UUID target.
        assert out["status"] == "sent"
        assert adapter.sent[0].to == ["anon.donor@example.com"]

    def test_in_app_skips_for_anonymous_target(self, workspace_factory):
        run = self._anon_run(workspace_factory())
        config = {"channel": "in_app", "body": "Thanks!"}

        # Must NOT raise "not a valid UUID" — an anonymous donor has no in-app
        # inbox, so the node skips gracefully and the run continues.
        out = execute_node_action(run, _node("message", config), config)
        assert out["status"] == "skipped"
