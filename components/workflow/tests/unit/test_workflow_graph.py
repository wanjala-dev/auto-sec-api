"""Unit tests for WorkflowGraph navigation + branch selection (pure domain)."""

from __future__ import annotations

from components.workflow.domain.value_objects.workflow_graph import WorkflowGraph


def _graph():
    return {
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "cond", "type": "condition"},
            {"id": "yes_node", "type": "message"},
            {"id": "no_node", "type": "message"},
            {"id": "end", "type": "end"},
        ],
        "edges": [
            {"id": "e1", "from": "start", "to": "cond"},
            {"id": "e2", "from": "cond", "to": "yes_node", "label": "yes"},
            {"id": "e3", "from": "cond", "to": "no_node", "label": "no"},
            {"id": "e4", "from": "yes_node", "to": "end"},
        ],
    }


class TestNavigation:
    def test_start_node(self):
        assert WorkflowGraph(_graph()).start_node_id() == "start"

    def test_start_node_requires_exactly_one(self):
        g = _graph()
        g["nodes"].append({"id": "start2", "type": "start"})
        assert WorkflowGraph(g).start_node_id() is None

    def test_default_target_is_first_edge(self):
        assert WorkflowGraph(_graph()).default_target("start") == "cond"

    def test_node_type(self):
        assert WorkflowGraph(_graph()).node_type("cond") == "condition"

    def test_empty_graph(self):
        g = WorkflowGraph(None)
        assert g.start_node_id() is None
        assert g.default_target("x") is None
        assert g.branch_target("x", True) is None


class TestBranchSelection:
    def test_boolean_picks_labelled_edge(self):
        g = WorkflowGraph(_graph())
        assert g.branch_target("cond", True) == "yes_node"
        assert g.branch_target("cond", False) == "no_node"

    def test_boolean_positional_fallback_without_labels(self):
        graph = {
            "nodes": [{"id": "c", "type": "condition"}, {"id": "a", "type": "end"}, {"id": "b", "type": "end"}],
            "edges": [{"id": "e1", "from": "c", "to": "a"}, {"id": "e2", "from": "c", "to": "b"}],
        }
        g = WorkflowGraph(graph)
        assert g.branch_target("c", True) == "a"   # first = yes
        assert g.branch_target("c", False) == "b"  # second = no

    def test_synonym_labels(self):
        graph = {
            "nodes": [{"id": "c", "type": "wait_until"}],
            "edges": [
                {"id": "e1", "from": "c", "to": "hit", "label": "satisfied"},
                {"id": "e2", "from": "c", "to": "miss", "label": "timeout"},
            ],
        }
        g = WorkflowGraph(graph)
        assert g.branch_target("c", True) == "hit"
        assert g.branch_target("c", False) == "miss"

    def test_legacy_string_outcome_matches_label(self):
        g = WorkflowGraph(_graph())
        assert g.branch_target("cond", "no") == "no_node"

    def test_single_edge_both_outcomes(self):
        graph = {
            "nodes": [{"id": "c", "type": "condition"}],
            "edges": [{"id": "e1", "from": "c", "to": "only"}],
        }
        g = WorkflowGraph(graph)
        assert g.branch_target("c", True) == "only"
        assert g.branch_target("c", False) == "only"
