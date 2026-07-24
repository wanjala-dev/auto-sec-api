"""Regression: a workspace-wide binding (source_id NULL) must fire for events
that carry a source_id.

Publishing a workflow creates an auto-managed binding with ``source_id IS NULL``
(fire for ANY source). The dispatcher previously filtered
``source_id__in=[event.source_id, None, ""]`` — but SQL ``IN (..., NULL)`` never
matches NULL rows, so every workspace-wide binding silently dropped any event
that carried a source_id (donations / sponsorships / form donations all carry
``recipient_id`` as source_id). Result: published workflows never ran. This test
locks the fix: a NULL-source binding fires whether or not the event is scoped.
"""

from __future__ import annotations

import pytest

from components.workflow.application.service import WorkflowService
from components.workflow.infrastructure.adapters.dispatcher import dispatch_event
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowBinding,
    WorkflowEvent,
    WorkflowRun,
)

pytestmark = [pytest.mark.django_db]


def _graph():
    return {
        "nodes": [
            {"id": "start", "type": "start", "label": "Start",
             "config": {"triggerTypes": ["finding_raised"]}},
            {"id": "msg", "type": "message", "label": "Notify",
             "config": {"channel": "in_app", "body": "thanks"}},
            {"id": "end", "type": "end", "label": "End", "config": {}},
        ],
        "edges": [
            {"id": "e0", "from": "start", "to": "msg"},
            {"id": "e1", "from": "msg", "to": "end"},
        ],
    }


def _publish(workspace):
    wf = Workflow.objects.create(
        workspace=workspace, name="Donation notify", goal="general",
        status="draft", graph=_graph(),
    )
    WorkflowService().publish_workflow(wf)
    return wf


def _event(workspace, *, source_id, target_id="contact-1"):
    return WorkflowEvent.objects.create(
        workspace_id=str(workspace.id),
        source_type="finding",
        source_id=source_id,
        trigger_type="finding_raised",
        payload={"target_type": "contact", "target_id": target_id, "amount": "25.00"},
    )


class TestNullSourceBindingFires:
    def test_workspace_wide_binding_fires_for_scoped_event(self, workspace_factory):
        ws = workspace_factory()
        _publish(ws)
        # sanity: publish made exactly one NULL-source binding
        binding = WorkflowBinding.objects.get(
            workflow__workspace_id=ws.id, trigger_type="finding_raised"
        )
        assert binding.source_id is None

        # event carries a source_id (e.g. the recipient) — the regression case
        created = dispatch_event(_event(ws, source_id="recipient-xyz"))

        assert created == 1
        assert WorkflowRun.objects.filter(workflow__workspace_id=ws.id).count() == 1

    def test_workspace_wide_binding_fires_for_unscoped_event(self, workspace_factory):
        ws = workspace_factory()
        _publish(ws)
        created = dispatch_event(_event(ws, source_id=None))
        assert created == 1

    def test_source_scoped_binding_only_fires_for_its_source(self, workspace_factory):
        ws = workspace_factory()
        wf = _publish(ws)
        # narrow the auto binding to one source
        WorkflowBinding.objects.filter(workflow=wf).update(source_id="recipient-A")

        assert dispatch_event(_event(ws, source_id="recipient-B")) == 0
        assert dispatch_event(_event(ws, source_id="recipient-A")) == 1
