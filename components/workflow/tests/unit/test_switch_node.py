"""Unit tests for the autonomous multi-way ``switch`` node.

A switch evaluates an ordered list of cases (same predicate DSL as ``condition``)
and resolves to the first matching case's label; the engine then takes that
labelled edge. Falls through to ``default_label`` when no case matches.
"""

from __future__ import annotations

import pytest

from components.workflow.domain.errors import WorkflowConditionError
from components.workflow.domain.services.condition_evaluator import evaluate_switch
from components.workflow.domain.validators import validate_graph
from components.workflow.domain.value_objects.workflow_graph import WorkflowGraph

pytestmark = pytest.mark.unit


def _switch_config():
    return {
        "cases": [
            {"label": "major", "predicate": {"conditions": [{"field": "amount", "op": "gte", "value": 500}]}},
            {"label": "mid", "predicate": {"conditions": [{"field": "amount", "op": "gte", "value": 100}]}},
        ],
        "default_label": "small",
    }


class TestEvaluateSwitch:
    def test_first_matching_case_wins(self):
        assert evaluate_switch(_switch_config(), {"amount": 750}) == "major"

    def test_order_matters_second_case(self):
        assert evaluate_switch(_switch_config(), {"amount": 250}) == "mid"

    def test_falls_through_to_default(self):
        assert evaluate_switch(_switch_config(), {"amount": 20}) == "small"

    def test_missing_field_falls_through(self):
        # amount absent -> no numeric case matches -> default
        assert evaluate_switch(_switch_config(), {}) == "small"

    def test_no_default_returns_none(self):
        cfg = {"cases": [{"label": "yes", "predicate": {"conditions": [{"field": "x", "op": "eq", "value": 1}]}}]}
        assert evaluate_switch(cfg, {"x": 2}) is None

    def test_empty_cases_returns_default(self):
        assert evaluate_switch({"cases": [], "default_label": "d"}, {}) == "d"

    def test_case_without_label_raises(self):
        with pytest.raises(WorkflowConditionError):
            evaluate_switch({"cases": [{"predicate": {}}]}, {})

    def test_non_dict_config_raises(self):
        with pytest.raises(WorkflowConditionError):
            evaluate_switch([], {})


class TestSwitchValidation:
    def _graph(self, switch_config, edges):
        return {
            "nodes": [
                {"id": "start", "type": "start", "label": "Start", "config": {}},
                {"id": "sw", "type": "switch", "label": "Route", "config": switch_config},
                {"id": "a", "type": "end", "label": "A", "config": {}},
                {"id": "b", "type": "end", "label": "B", "config": {}},
            ],
            "edges": [{"id": "e0", "from": "start", "to": "sw"}, *edges],
        }

    def test_valid_switch_passes(self):
        graph = self._graph(
            _switch_config(),
            [
                {"id": "e1", "from": "sw", "to": "a", "label": "major"},
                {"id": "e2", "from": "sw", "to": "b", "label": "small"},
            ],
        )
        assert validate_graph(graph) == []

    def test_switch_without_cases_fails(self):
        graph = self._graph(
            {},
            [
                {"id": "e1", "from": "sw", "to": "a", "label": "x"},
                {"id": "e2", "from": "sw", "to": "b", "label": "y"},
            ],
        )
        codes = {e["code"] for e in validate_graph(graph)}
        assert "switch_missing_cases" in codes

    def test_switch_with_one_edge_fails(self):
        graph = self._graph(
            _switch_config(),
            [{"id": "e1", "from": "sw", "to": "a", "label": "major"}],
        )
        codes = {e["code"] for e in validate_graph(graph)}
        assert "branch_missing_branches" in codes


class TestSwitchBranchResolution:
    def test_label_outcome_picks_matching_edge(self):
        graph = WorkflowGraph(
            {
                "nodes": [
                    {"id": "sw", "type": "switch", "label": "Route"},
                    {"id": "a", "type": "end", "label": "A"},
                    {"id": "b", "type": "end", "label": "B"},
                    {"id": "c", "type": "end", "label": "C"},
                ],
                "edges": [
                    {"id": "e1", "from": "sw", "to": "a", "label": "major"},
                    {"id": "e2", "from": "sw", "to": "b", "label": "mid"},
                    {"id": "e3", "from": "sw", "to": "c", "label": "small"},
                ],
            }
        )
        assert graph.branch_target("sw", "mid") == "b"
        assert graph.branch_target("sw", "small") == "c"
        # Unknown / None label falls back to the first edge.
        assert graph.branch_target("sw", None) == "a"
