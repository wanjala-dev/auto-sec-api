"""Publishing a workflow wires up one binding per start-node trigger.

A single start node can carry multiple triggers (config.triggerTypes) so several
events route into one workflow. On publish, WorkflowService reconciles exactly one
ACTIVE auto-managed binding (source_id IS NULL) per selected trigger, and
deactivates auto-managed bindings for triggers that were removed. Manually-created
source-scoped bindings are never touched.
"""

from __future__ import annotations

import pytest

from components.workflow.application.service import WorkflowService
from infrastructure.persistence.workspaces.workflows.models import (
    Workflow,
    WorkflowBinding,
)

pytestmark = [pytest.mark.django_db]


def _graph(trigger_types):
    return {
        "nodes": [
            {
                "id": "start",
                "type": "start",
                "label": "Start",
                "config": {"triggerTypes": trigger_types},
            },
            {"id": "msg", "type": "message", "label": "Welcome",
             "config": {"channel": "email", "body": "hi"}},
            {"id": "end", "type": "end", "label": "End", "config": {}},
        ],
        "edges": [
            {"id": "e0", "from": "start", "to": "msg"},
            {"id": "e1", "from": "msg", "to": "end"},
        ],
    }


def _make_workflow(workspace, trigger_types):
    return Workflow.objects.create(
        workspace=workspace,
        name="Multi-trigger",
        goal="general",
        status="draft",
        graph=_graph(trigger_types),
    )


class TestPublishSyncsBindings:
    def test_one_binding_per_trigger(self, workspace_factory):
        ws = workspace_factory()
        wf = _make_workflow(ws, ["contact_added", "donation_received"])

        WorkflowService().publish_workflow(wf)

        bindings = WorkflowBinding.objects.filter(workflow_id=wf.id, is_active=True)
        triggers = {b.trigger_type for b in bindings}
        assert triggers == {"contact_added", "donation_received"}
        # source_type is resolved from the trigger catalog
        by_trigger = {b.trigger_type: b.source_type for b in bindings}
        assert by_trigger["contact_added"] == "directory"
        assert by_trigger["donation_received"] == "sponsorship"

    def test_removing_a_trigger_deactivates_its_binding(self, workspace_factory):
        ws = workspace_factory()
        wf = _make_workflow(ws, ["contact_added", "donation_received"])
        WorkflowService().publish_workflow(wf)

        # Re-publish with one trigger removed.
        wf.graph = _graph(["contact_added"])
        wf.save(update_fields=["graph"])
        WorkflowService().publish_workflow(wf)

        active = {
            b.trigger_type
            for b in WorkflowBinding.objects.filter(workflow_id=wf.id, is_active=True)
        }
        assert active == {"contact_added"}
        # the removed trigger's binding still exists but is inactive (no dupes)
        donation = WorkflowBinding.objects.filter(
            workflow_id=wf.id, trigger_type="donation_received"
        )
        assert donation.count() == 1
        assert donation.first().is_active is False

    def test_republish_is_idempotent(self, workspace_factory):
        ws = workspace_factory()
        wf = _make_workflow(ws, ["contact_added"])
        WorkflowService().publish_workflow(wf)
        WorkflowService().publish_workflow(wf)
        assert WorkflowBinding.objects.filter(
            workflow_id=wf.id, trigger_type="contact_added"
        ).count() == 1

    def test_manual_source_scoped_binding_untouched(self, workspace_factory):
        ws = workspace_factory()
        wf = _make_workflow(ws, ["contact_added"])
        manual = WorkflowBinding.objects.create(
            workflow_id=wf.id,
            source_type="campaign",
            trigger_type="campaign_opened",
            source_id="some-campaign-id",
            is_active=True,
        )
        WorkflowService().publish_workflow(wf)
        manual.refresh_from_db()
        assert manual.is_active is True  # source-scoped binding left alone


class TestStartNodeTriggerExtraction:
    def test_extracts_triggertypes_list_and_single(self):
        graph = {
            "nodes": [
                {
                    "id": "start",
                    "type": "start",
                    "config": {
                        "triggerTypes": ["contact_added"],
                        "triggerType": "donation_received",
                    },
                }
            ]
        }
        pairs = WorkflowService._start_node_triggers(graph)
        triggers = {t for _, t in pairs}
        assert triggers == {"contact_added", "donation_received"}

    def test_unknown_trigger_skipped(self):
        graph = {"nodes": [{"id": "start", "type": "start",
                            "config": {"triggerTypes": ["not_a_real_trigger"]}}]}
        assert WorkflowService._start_node_triggers(graph) == []
