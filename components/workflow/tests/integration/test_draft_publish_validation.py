"""Draft-save vs publish validation split.

A draft is incomplete by nature — picking a template and clicking "Save draft"
must succeed even though template nodes aren't fully configured. Full per-node
validation is enforced only at PUBLISH time. (Surfaced by the Phase 3 builder
E2E: Save draft on a template 400'd because create strict-validated the graph.)
"""

from __future__ import annotations

import pytest

from components.workflow.application.service import WorkflowService
from components.workflow.domain.constants import TRIGGER_CATALOG
from components.workflow.domain.errors import WorkflowGraphValidationError
from components.workflow.mappers.rest.workflow_serializers import WorkflowSerializer
from infrastructure.persistence.workspaces.workflows.models import Workflow

pytestmark = pytest.mark.django_db


# An incomplete-but-structural graph: a message node with no channel/body, like
# a freshly-picked template before the user configures it.
_INCOMPLETE_GRAPH = {
    "nodes": [
        {"id": "start", "type": "start", "label": "Start"},
        {"id": "msg", "type": "message", "label": "Send Message", "config": {}},
        {"id": "end", "type": "end", "label": "End"},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "msg"},
        {"id": "e2", "from": "msg", "to": "end"},
    ],
}

# A fully-configured, valid graph.
_VALID_GRAPH = {
    "nodes": [
        {"id": "start", "type": "start", "label": "Start"},
        {
            "id": "msg",
            "type": "message",
            "label": "Thank you",
            "config": {"channel": "email", "subject": "Thanks!", "body": "Thank you for giving."},
        },
        {"id": "end", "type": "end", "label": "End"},
    ],
    "edges": [
        {"id": "e1", "from": "start", "to": "msg"},
        {"id": "e2", "from": "msg", "to": "end"},
    ],
}


class TestDraftSaveAllowsIncompleteGraph:
    def test_create_serializer_accepts_incomplete_draft(self, workspace_factory):
        ws = workspace_factory()
        serializer = WorkflowSerializer(
            data={
                "workspace_id": str(ws.id),
                "name": "Incomplete draft",
                "goal": "general",
                "graph": _INCOMPLETE_GRAPH,
                "status": "draft",
            }
        )
        assert serializer.is_valid(), serializer.errors

    def test_create_serializer_rejects_non_graph(self, workspace_factory):
        ws = workspace_factory()
        serializer = WorkflowSerializer(
            data={
                "workspace_id": str(ws.id),
                "name": "Bad graph",
                "goal": "general",
                "graph": {"nodes": "nope"},
                "status": "draft",
            }
        )
        assert not serializer.is_valid()
        assert "graph" in serializer.errors


class TestPublishIsTheValidationGate:
    def test_publish_rejects_incomplete_graph(self, workspace_factory):
        ws = workspace_factory()
        wf = Workflow.objects.create(
            workspace=ws, name="D", goal="general",
            status=Workflow.Status.DRAFT, version=1, graph=_INCOMPLETE_GRAPH,
        )
        with pytest.raises(WorkflowGraphValidationError):
            WorkflowService().publish_workflow(wf)

    def test_publish_accepts_valid_graph(self, workspace_factory):
        ws = workspace_factory()
        wf = Workflow.objects.create(
            workspace=ws, name="V", goal="general",
            status=Workflow.Status.DRAFT, version=1, graph=_VALID_GRAPH,
        )
        result = WorkflowService().publish_workflow(wf)
        assert result.status == Workflow.Status.PUBLISHED


class TestTaskAssignedTriggerBindable:
    def test_task_assigned_is_in_catalog(self):
        # Emitted by project assignment; must be catalogued to be bindable.
        ids = {t.id for t in TRIGGER_CATALOG}
        assert "task_assigned" in ids
