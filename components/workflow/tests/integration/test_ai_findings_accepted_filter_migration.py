"""The ai-findings-accepted filter cutover (workflows migration 0004, ADR 0030 P3).

Human accept = the canonical Complete lane now; the template AND every
per-workspace clone must watch it — a clone left on "Accepted" would silently
never fire ``TaskAcceptedFromBoard`` again. Both directions exercised via the
migration functions against real models (established migration-test pattern).
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from infrastructure.persistence.workspaces.workflows.models import Workflow, WorkflowTemplate

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_migration = importlib.import_module(
    "infrastructure.persistence.workspaces.workflows.migrations.0004_ai_findings_accepted_filter_complete"
)


class _SchemaEditorStub:
    class connection:
        alias = "default"


def _graph(title):
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {"triggerType": "task_moved_column"}},
            {
                "id": "publish",
                "type": "publish_event",
                "config": {
                    "event_type": "task_accepted_from_board",
                    "filters": {"task_source_type_prefix": "ai.", "new_column_title": title},
                },
            },
        ],
        "edges": [{"id": "e0", "from": "start", "to": "publish"}],
    }


def _publish_filter(graph):
    return graph["nodes"][1]["config"]["filters"]["new_column_title"]


def _seed(workspace_factory, *, title="Accepted"):
    workspace = workspace_factory()
    template = WorkflowTemplate.objects.create(
        id="ai-findings-accepted",
        label="AI Findings Accepted",
        category="agents",
        is_system=True,
        default_graph=_graph(title),
    )
    clone = Workflow.objects.create(
        workspace=workspace,
        name="AI Findings Accepted",
        goal="agents",
        template=template,
        status="published",
        graph=_graph(title),
    )
    unrelated = Workflow.objects.create(
        workspace=workspace,
        name="Unrelated",
        goal="ops",
        graph=_graph(title),  # same shape but NOT cloned from the template
    )
    return template, clone, unrelated


def test_forward_repoints_template_and_clones_only(workspace_factory):
    template, clone, unrelated = _seed(workspace_factory)

    _migration.forwards(django_apps, _SchemaEditorStub())

    template.refresh_from_db()
    clone.refresh_from_db()
    unrelated.refresh_from_db()
    assert _publish_filter(template.default_graph) == "Complete"
    assert _publish_filter(clone.graph) == "Complete"
    assert _publish_filter(unrelated.graph) == "Accepted"  # not template-cloned → untouched


def test_backwards_restores_accepted(workspace_factory):
    template, clone, _unrelated = _seed(workspace_factory)

    _migration.forwards(django_apps, _SchemaEditorStub())
    _migration.backwards(django_apps, _SchemaEditorStub())

    template.refresh_from_db()
    clone.refresh_from_db()
    assert _publish_filter(template.default_graph) == "Accepted"
    assert _publish_filter(clone.graph) == "Accepted"


def test_forward_is_rerunnable(workspace_factory):
    _template, clone, _unrelated = _seed(workspace_factory)

    _migration.forwards(django_apps, _SchemaEditorStub())
    _migration.forwards(django_apps, _SchemaEditorStub())

    clone.refresh_from_db()
    assert _publish_filter(clone.graph) == "Complete"
