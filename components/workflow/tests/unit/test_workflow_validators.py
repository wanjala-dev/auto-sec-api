"""Unit tests for workflow graph validators — pure functions, no Django dependencies."""

from __future__ import annotations

import pytest

from components.workflow.domain.validators import validate_graph


class TestValidateGraphBasicStructure:
    """Tests for basic graph structure validation."""

    def test_valid_minimal_graph(self):
        """Should accept minimal valid graph with start and end nodes."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [{"from": "start", "to": "end"}],
        }

        errors = validate_graph(graph)

        assert errors == []

    def test_graph_missing_nodes_key(self):
        """Should reject graph without 'nodes' key."""
        graph = {"edges": []}

        errors = validate_graph(graph)

        assert len(errors) > 0
        assert errors[0]["code"] == "invalid_graph"
        assert "nodes" in errors[0]["message"].lower()

    def test_graph_missing_edges_key(self):
        """Should reject graph without 'edges' key."""
        graph = {"nodes": []}

        errors = validate_graph(graph)

        assert len(errors) > 0
        assert errors[0]["code"] == "invalid_graph"
        assert "edges" in errors[0]["message"].lower()

    def test_graph_not_a_dict(self):
        """Should reject non-dict graph."""
        graph = None

        errors = validate_graph(graph)

        assert len(errors) > 0
        assert errors[0]["code"] == "invalid_graph"

    def test_nodes_not_a_list(self):
        """Should reject non-list nodes."""
        graph = {
            "nodes": {"id": "start"},
            "edges": [],
        }

        errors = validate_graph(graph)

        assert len(errors) > 0
        assert errors[0]["code"] == "invalid_graph"

    def test_edges_not_a_list(self):
        """Should reject non-list edges."""
        graph = {
            "nodes": [],
            "edges": {"from": "start", "to": "end"},
        }

        errors = validate_graph(graph)

        assert len(errors) > 0
        assert errors[0]["code"] == "invalid_graph"


class TestValidateGraphNodeLimits:
    """Tests for node and edge count limits."""

    def test_graph_exceeds_max_nodes(self):
        """Should reject graph with more than MAX_NODES nodes."""
        nodes = [
            {"id": f"node-{i}", "type": "start" if i == 0 else "end" if i == 250 else "task", "title": f"Node {i}"}
            for i in range(251)
        ]
        edges = []

        graph = {"nodes": nodes, "edges": edges}

        errors = validate_graph(graph)

        assert any(e["code"] == "graph_too_large" for e in errors)
        assert any("250" in e["message"] for e in errors)

    def test_graph_exceeds_max_edges(self):
        """Should reject graph with more than MAX_EDGES edges."""
        nodes = [
            {"id": "start", "type": "start", "title": "Start"},
            {"id": "end", "type": "end", "title": "End"},
        ]
        edges = [{"from": "start", "to": "end"} for _ in range(501)]

        graph = {"nodes": nodes, "edges": edges}

        errors = validate_graph(graph)

        assert any(e["code"] == "graph_too_large" for e in errors)
        assert any("500" in e["message"] for e in errors)

    def test_graph_at_max_nodes_limit(self):
        """Should accept graph at exactly MAX_NODES."""
        nodes = [
            {"id": f"node-{i}", "type": "start" if i == 0 else "end" if i == 249 else "task", "title": f"Node {i}"}
            for i in range(250)
        ]
        edges = [{"from": f"node-{i}", "to": f"node-{i+1}"} for i in range(249)]

        graph = {"nodes": nodes, "edges": edges}

        errors = validate_graph(graph)

        # Should not have graph_too_large error for nodes
        assert not any(e["code"] == "graph_too_large" and "Node count" in e["message"] for e in errors)

    def test_graph_at_max_edges_limit(self):
        """Should accept graph at exactly MAX_EDGES."""
        nodes = [
            {"id": "start", "type": "start", "title": "Start"},
            {"id": "end", "type": "end", "title": "End"},
        ]
        edges = [{"from": "start", "to": "end"} for _ in range(500)]

        graph = {"nodes": nodes, "edges": edges}

        errors = validate_graph(graph)

        # Should not have graph_too_large error for edges
        assert not any(e["code"] == "graph_too_large" and "Edge count" in e["message"] for e in errors)


class TestValidateGraphNodes:
    """Tests for node validation."""

    def test_node_missing_id(self):
        """Should reject node without id."""
        graph = {
            "nodes": [
                {"type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "missing_node_id" for e in errors)

    def test_node_missing_type(self):
        """Should reject node without type."""
        graph = {
            "nodes": [
                {"id": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_node_type" for e in errors)

    def test_node_missing_title(self):
        """Should reject node without title."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "missing_node_title" for e in errors)

    def test_node_with_empty_title(self):
        """Should reject node with empty title."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": ""},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "missing_node_title" for e in errors)

    def test_node_invalid_type(self):
        """Should reject node with invalid type."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "bad", "type": "invalid_type", "title": "Bad"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_node_type" for e in errors)
        assert any("invalid_type" in e["message"] for e in errors)

    def test_node_not_a_dict(self):
        """Should reject node that is not a dict."""
        graph = {
            "nodes": [
                "not a dict",
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_node" for e in errors)

    def test_duplicate_node_ids(self):
        """Should reject graph with duplicate node IDs."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "duplicate", "type": "task", "title": "Task 1"},
                {"id": "duplicate", "type": "task", "title": "Task 2"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "duplicate_node_ids" for e in errors)
        assert any("duplicate" in e["message"] for e in errors)

    def test_multiple_duplicate_node_ids(self):
        """Should report all duplicate node IDs."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "dup1", "type": "task", "title": "Task 1a"},
                {"id": "dup1", "type": "task", "title": "Task 1b"},
                {"id": "dup2", "type": "task", "title": "Task 2a"},
                {"id": "dup2", "type": "task", "title": "Task 2b"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [],
        }

        errors = validate_graph(graph)

        dup_errors = [e for e in errors if e["code"] == "duplicate_node_ids"]
        assert len(dup_errors) > 0
        assert any("dup1" in e["message"] for e in dup_errors)
        assert any("dup2" in e["message"] for e in dup_errors)


class TestValidateGraphEdges:
    """Tests for edge validation."""

    def test_edge_not_a_dict(self):
        """Should reject edge that is not a dict."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": ["not a dict"],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_edge" for e in errors)

    def test_edge_missing_from(self):
        """Should reject edge without 'from' field."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [{"to": "end"}],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_edge_reference" for e in errors)

    def test_edge_missing_to(self):
        """Should reject edge without 'to' field."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [{"from": "start"}],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_edge_reference" for e in errors)

    def test_edge_references_nonexistent_source(self):
        """Should reject edge referencing non-existent source node."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [{"from": "unknown", "to": "end"}],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "unknown_edge_source" for e in errors)
        assert any("unknown" in e["message"] for e in errors)

    def test_edge_references_nonexistent_target(self):
        """Should reject edge referencing non-existent target node."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [{"from": "start", "to": "unknown"}],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "unknown_edge_target" for e in errors)
        assert any("unknown" in e["message"] for e in errors)


class TestValidateGraphStartAndEndNodes:
    """Tests for start and end node requirements."""

    def test_graph_missing_start_node(self):
        """Should reject graph without start node."""
        graph = {
            "nodes": [
                {"id": "task", "type": "task", "title": "Do something"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [{"from": "task", "to": "end"}],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_start_node" for e in errors)

    def test_graph_multiple_start_nodes(self):
        """Should reject graph with multiple start nodes."""
        graph = {
            "nodes": [
                {"id": "start1", "type": "start", "title": "Begin 1"},
                {"id": "start2", "type": "start", "title": "Begin 2"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start1", "to": "end"},
                {"from": "start2", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "invalid_start_node" for e in errors)

    def test_graph_missing_end_node(self):
        """Should reject graph without end node."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "task", "type": "task", "title": "Do something"},
            ],
            "edges": [{"from": "start", "to": "task"}],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "missing_end_node" for e in errors)

    def test_graph_multiple_end_nodes(self):
        """Should accept graph with multiple end nodes."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "end1", "type": "end", "title": "Success"},
                {"id": "end2", "type": "end", "title": "Failure"},
            ],
            "edges": [
                {"from": "start", "to": "end1"},
                {"from": "start", "to": "end2"},
            ],
        }

        errors = validate_graph(graph)

        # Should not have missing_end_node error
        assert not any(e["code"] == "missing_end_node" for e in errors)


class TestValidateGraphDecisionNodes:
    """Tests for decision node validation."""

    def test_decision_node_requires_two_edges(self):
        """Should require at least 2 outgoing edges from decision node."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "decision", "type": "decision", "title": "Choose"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "decision"},
                {"from": "decision", "to": "end"},  # Only 1 outgoing
            ],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "branch_missing_branches" for e in errors)

    def test_decision_node_with_two_branches(self):
        """Should accept decision node with exactly 2 branches."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "decision", "type": "decision", "title": "Choose"},
                {"id": "end1", "type": "end", "title": "Yes"},
                {"id": "end2", "type": "end", "title": "No"},
            ],
            "edges": [
                {"from": "start", "to": "decision"},
                {"from": "decision", "to": "end1", "label": "Yes"},
                {"from": "decision", "to": "end2", "label": "No"},
            ],
        }

        errors = validate_graph(graph)

        assert not any(e["code"] == "branch_missing_branches" for e in errors)
        assert not any(e["code"] == "branch_missing_label" for e in errors)

    def test_decision_edge_missing_label(self):
        """Should require labels on decision node edges."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "decision", "type": "decision", "title": "Choose"},
                {"id": "end1", "type": "end", "title": "Yes"},
                {"id": "end2", "type": "end", "title": "No"},
            ],
            "edges": [
                {"from": "start", "to": "decision"},
                {"from": "decision", "to": "end1", "label": "Yes"},
                {"from": "decision", "to": "end2"},  # Missing label
            ],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "branch_missing_label" for e in errors)

    def test_decision_with_multiple_branches(self):
        """Should accept decision node with more than 2 branches."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "decision", "type": "decision", "title": "Choose"},
                {"id": "end1", "type": "end", "title": "Option 1"},
                {"id": "end2", "type": "end", "title": "Option 2"},
                {"id": "end3", "type": "end", "title": "Option 3"},
            ],
            "edges": [
                {"from": "start", "to": "decision"},
                {"from": "decision", "to": "end1", "label": "Option 1"},
                {"from": "decision", "to": "end2", "label": "Option 2"},
                {"from": "decision", "to": "end3", "label": "Option 3"},
            ],
        }

        errors = validate_graph(graph)

        assert not any(e["code"] == "branch_missing_branches" for e in errors)


class TestValidateGraphWaitNodes:
    """Tests for wait node validation."""

    def test_wait_node_missing_delay(self):
        """Should reject wait node without delay_seconds or delay_until."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "wait", "type": "wait", "title": "Wait", "config": {}},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "wait"},
                {"from": "wait", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "wait_missing_delay" for e in errors)

    def test_wait_node_with_delay_seconds(self):
        """Should accept wait node with delay_seconds."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {
                    "id": "wait",
                    "type": "wait",
                    "title": "Wait",
                    "config": {"delay_seconds": 3600},
                },
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "wait"},
                {"from": "wait", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert not any(e["code"] == "wait_missing_delay" for e in errors)

    def test_wait_node_with_delay_until(self):
        """Should accept wait node with delay_until."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {
                    "id": "wait",
                    "type": "wait",
                    "title": "Wait",
                    "config": {"delay_until": "2025-12-31T23:59:59Z"},
                },
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "wait"},
                {"from": "wait", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert not any(e["code"] == "wait_missing_delay" for e in errors)

    def test_wait_node_missing_config(self):
        """Should reject wait node with missing config."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "wait", "type": "wait", "title": "Wait"},
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "wait"},
                {"from": "wait", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "wait_missing_delay" for e in errors)


class TestValidateGraphMessageNodes:
    """Tests for message node validation."""

    def test_message_node_missing_channel(self):
        """Should reject message node without channel."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {
                    "id": "message",
                    "type": "message",
                    "title": "Send message",
                    "config": {"message": "Hello"},
                },
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "message"},
                {"from": "message", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "message_missing_channel" for e in errors)

    def test_message_node_missing_payload(self):
        """Should reject message node without message content."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {
                    "id": "message",
                    "type": "message",
                    "title": "Send message",
                    "config": {"channel": "email"},
                },
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "message"},
                {"from": "message", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert any(e["code"] == "message_missing_payload" for e in errors)

    def test_message_node_with_template_id(self):
        """Should accept message node with template_id."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {
                    "id": "message",
                    "type": "message",
                    "title": "Send message",
                    "config": {"channel": "email", "template_id": "welcome-email"},
                },
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "message"},
                {"from": "message", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert not any(e["code"] == "message_missing_payload" for e in errors)
        assert not any(e["code"] == "message_missing_channel" for e in errors)

    def test_message_node_with_message_text(self):
        """Should accept message node with message text."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {
                    "id": "message",
                    "type": "message",
                    "title": "Send message",
                    "config": {"channel": "sms", "message": "Hello world"},
                },
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "message"},
                {"from": "message", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert not any(e["code"] == "message_missing_payload" for e in errors)

    def test_message_node_with_body_field(self):
        """Should accept message node with body field."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {
                    "id": "message",
                    "type": "message",
                    "title": "Send message",
                    "config": {"channel": "push", "body": "Notification text"},
                },
                {"id": "end", "type": "end", "title": "Finish"},
            ],
            "edges": [
                {"from": "start", "to": "message"},
                {"from": "message", "to": "end"},
            ],
        }

        errors = validate_graph(graph)

        assert not any(e["code"] == "message_missing_payload" for e in errors)


class TestValidateGraphComplexScenarios:
    """Integration tests for complex graph scenarios."""

    def test_valid_complex_workflow(self):
        """Should validate a realistic complex workflow."""
        graph = {
            "nodes": [
                {"id": "start", "type": "start", "title": "Begin"},
                {"id": "task1", "type": "task", "title": "Process"},
                {"id": "decision", "type": "decision", "title": "Check"},
                {"id": "task2", "type": "task", "title": "Approve"},
                {"id": "message", "type": "message", "title": "Notify", "config": {"channel": "email", "message": "Done"}},
                {"id": "end1", "type": "end", "title": "Success"},
                {"id": "end2", "type": "end", "title": "Reject"},
            ],
            "edges": [
                {"from": "start", "to": "task1"},
                {"from": "task1", "to": "decision"},
                {"from": "decision", "to": "task2", "label": "Approved"},
                {"from": "decision", "to": "end2", "label": "Rejected"},
                {"from": "task2", "to": "message"},
                {"from": "message", "to": "end1"},
            ],
        }

        errors = validate_graph(graph)

        assert errors == []

    def test_graph_with_multiple_validation_errors(self):
        """Should report all validation errors together."""
        graph = {
            "nodes": [
                {"id": "start", "type": "invalid", "title": "Begin"},  # Invalid type
                {"id": "task1", "type": "task"},  # Missing title
                {"id": "task1", "type": "task", "title": "Duplicate"},  # Duplicate ID
                # Missing end node
            ],
            "edges": [
                {"from": "start", "to": "unknown"},  # Unknown target
            ],
        }

        errors = validate_graph(graph)

        assert len(errors) > 4
        error_codes = {e["code"] for e in errors}
        assert "invalid_node_type" in error_codes
        assert "missing_node_title" in error_codes
        assert "duplicate_node_ids" in error_codes
        assert "unknown_edge_target" in error_codes
        assert "missing_end_node" in error_codes
