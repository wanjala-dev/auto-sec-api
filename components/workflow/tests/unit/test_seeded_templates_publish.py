"""Every seeded system workflow template must be publish-ready.

This is the regression lock behind the templates library (B7 of the workflow GTM
overhaul): a user picks a template, clicks Publish, and it MUST publish — which
means its ``default_graph`` has to pass ``validate_graph`` (the exact gate
``WorkflowService.publish_workflow`` runs) with zero errors. These tests run the
real validator against the real seeded graphs, so editing a template into an
invalid shape fails here instead of failing a customer's Publish click.

Pure-domain: no DB, no Django fixtures — imports the seed list and the validator.
"""

from __future__ import annotations

import pytest

from components.workflow.cli.management.commands.seed_workflow_templates import (
    SYSTEM_TEMPLATES,
)
from components.workflow.domain.constants import NODE_TYPES, TRIGGER_CATALOG
from components.workflow.domain.services.condition_evaluator import evaluate_condition
from components.workflow.domain.validators import validate_graph
from components.workflow.domain.value_objects.workflow_graph import WorkflowGraph

pytestmark = pytest.mark.unit

_TEMPLATE_IDS = [t["id"] for t in SYSTEM_TEMPLATES]
_TRIGGER_IDS = {t.id for t in TRIGGER_CATALOG}
# trigger ids a ``wait_until`` node may await early (must be real, dispatchable
# trigger types so the dispatcher can wake the waiting step).
_BRANCH_NODE_TYPES = {"decision", "condition", "wait_until"}


@pytest.fixture(params=SYSTEM_TEMPLATES, ids=_TEMPLATE_IDS)
def template(request):
    return request.param


class TestSeededTemplatesPublish:
    def test_graph_passes_publish_validation(self, template):
        """The publish gate (validate_graph) returns zero errors."""
        errors = validate_graph(template["default_graph"])
        assert errors == [], (
            f"template {template['id']!r} would FAIL publish: {errors}"
        )

    def test_required_metadata_present(self, template):
        for field in ("id", "label", "category", "version", "description"):
            assert template.get(field), f"template {template['id']!r} missing {field}"

    def test_all_node_types_are_supported(self, template):
        for node in template["default_graph"]["nodes"]:
            assert node["type"] in NODE_TYPES, (
                f"template {template['id']!r} node {node['id']!r} uses "
                f"unknown type {node['type']!r}"
            )

    def test_start_node_carries_a_real_trigger(self, template):
        """The start node's triggerType hint must be a catalogued trigger."""
        start = next(
            n for n in template["default_graph"]["nodes"] if n["type"] == "start"
        )
        trigger = (start.get("config") or {}).get("triggerType")
        if trigger:  # not every legacy graph pins one; when present it must be real
            assert trigger in _TRIGGER_IDS, (
                f"template {template['id']!r} start trigger {trigger!r} not in catalog"
            )

    def test_wait_until_awaits_a_real_trigger(self, template):
        """A wait_until that names an ``event`` must name a dispatchable trigger."""
        for node in template["default_graph"]["nodes"]:
            if node["type"] != "wait_until":
                continue
            event = (node.get("config") or {}).get("event")
            assert event, (
                f"template {template['id']!r} wait_until {node['id']!r} has no event"
            )
            assert event in _TRIGGER_IDS, (
                f"template {template['id']!r} wait_until awaits {event!r} "
                f"which is not a catalogued trigger"
            )

    def test_branch_nodes_resolve_both_outcomes(self, template):
        """Every branch node resolves a distinct target for yes and no."""
        graph = WorkflowGraph(template["default_graph"])
        for node in template["default_graph"]["nodes"]:
            if node["type"] not in _BRANCH_NODE_TYPES:
                continue
            yes_target = graph.branch_target(node["id"], True)
            no_target = graph.branch_target(node["id"], False)
            assert yes_target, f"{template['id']}:{node['id']} has no yes target"
            assert no_target, f"{template['id']}:{node['id']} has no no target"

    def test_condition_predicates_are_evaluable(self, template):
        """Each condition node's predicate evaluates without raising."""
        for node in template["default_graph"]["nodes"]:
            if node["type"] != "condition":
                continue
            config = node.get("config") or {}
            predicate = config.get("predicate")
            if predicate is None and ("conditions" in config or "field" in config):
                predicate = config
            # Empty context -> missing fields -> should resolve False, not raise.
            outcome = evaluate_condition(predicate, {})
            assert isinstance(outcome, bool)


class TestStartTriggerAcceptedByDefaultGoal:
    """Every seeded template's start trigger must save under the default goal.

    A workflow created from a template gets goal ``general`` until the author
    picks a chip. The serializer validates the start node's trigger against the
    goal; ``general`` must impose no constraint, else every template-created
    workflow fails to save (the bug this locks)."""

    def test_general_goal_is_unconstrained(self):
        from components.workflow.mappers.rest.workflow_serializers import (
            _allowed_triggers_for_goal,
        )

        general = _allowed_triggers_for_goal("general")
        every = {t.id for t in TRIGGER_CATALOG}
        assert every <= general, f"general goal rejects {sorted(every - general)}"

    def test_every_template_start_trigger_saves_under_general(self, template):
        from components.workflow.mappers.rest.workflow_serializers import (
            _allowed_triggers_for_goal,
        )

        start = next(
            n for n in template["default_graph"]["nodes"] if n["type"] == "start"
        )
        trigger = (start.get("config") or {}).get("triggerType")
        if not trigger:
            pytest.skip("template start node has no triggerType")
        assert trigger in _allowed_triggers_for_goal("general"), (
            f"template {template['id']!r} start trigger {trigger!r} would be "
            f"rejected when saving with the default 'general' goal"
        )


class TestTemplateLibraryShape:
    def test_template_ids_are_unique(self):
        assert len(_TEMPLATE_IDS) == len(set(_TEMPLATE_IDS))

    def test_every_template_reaches_an_end(self):
        """From start, following default targets must reach an end node."""
        for template in SYSTEM_TEMPLATES:
            graph = WorkflowGraph(template["default_graph"])
            end_ids = {
                n["id"]
                for n in template["default_graph"]["nodes"]
                if n["type"] == "end"
            }
            # BFS over all outgoing edges from start; every template must be able
            # to reach at least one end node.
            start = graph.start_node_id()
            assert start, f"template {template['id']!r} has no single start node"
            seen, frontier = set(), [start]
            while frontier:
                node_id = frontier.pop()
                if node_id in seen:
                    continue
                seen.add(node_id)
                for edge in graph.edges_from(node_id):
                    frontier.append(edge["to"])
            assert seen & end_ids, (
                f"template {template['id']!r} cannot reach an end node"
            )
