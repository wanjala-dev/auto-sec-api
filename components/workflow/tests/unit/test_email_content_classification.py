"""Unit tests for the AI-vs-deterministic email content classifier.

``classify_email_content`` is a pure function (no DB, no send): given a message
node's config + the workflow graph, it decides whether the email content is
AI-derived (and must be gated for sign-off) or deterministic (sends as today).
Deterministic is the default; the AI path is reachable via an explicit marker or
ai->message chaining.
"""

from __future__ import annotations

from components.workflow.domain.value_objects.workflow_graph import WorkflowGraph
from components.workflow.infrastructure.adapters.node_actions import classify_email_content


def _graph(*node_types):
    return WorkflowGraph(
        {"nodes": [{"id": t, "type": t} for t in node_types], "edges": []}
    )


_NO_AI_GRAPH = _graph("start", "message", "end")
_AI_GRAPH = _graph("start", "ai", "message", "end")


class TestDeterministicByDefault:
    def test_plain_static_email_is_deterministic(self):
        config = {"channel": "email", "subject": "Hi", "body": "Thanks for your gift!"}
        assert classify_email_content(config, _NO_AI_GRAPH) == "deterministic"

    def test_template_email_is_deterministic(self):
        config = {"channel": "email", "template_id": "abc"}
        assert classify_email_content(config, _NO_AI_GRAPH) == "deterministic"

    def test_ai_node_in_graph_alone_does_not_gate_an_unwired_message(self):
        # An ai node exists but the message doesn't draw from it -> deterministic.
        config = {"channel": "email", "subject": "Hi", "body": "Static copy"}
        assert classify_email_content(config, _AI_GRAPH) == "deterministic"


class TestExplicitMarker:
    def test_ai_generated_flag_gates(self):
        config = {"channel": "email", "body": "AI copy", "ai_generated": True}
        assert classify_email_content(config, _NO_AI_GRAPH) == "ai"

    def test_content_source_ai_gates(self):
        config = {"channel": "email", "body": "AI copy", "content_source": "ai"}
        assert classify_email_content(config, _NO_AI_GRAPH) == "ai"


class TestChaining:
    def test_source_node_id_referencing_ai_node_gates(self):
        config = {"channel": "email", "body": "x", "source_node_id": "ai"}
        assert classify_email_content(config, _AI_GRAPH) == "ai"

    def test_steps_placeholder_referencing_ai_node_gates(self):
        config = {"channel": "email", "body": "{{steps.ai.result_preview}}"}
        assert classify_email_content(config, _AI_GRAPH) == "ai"

    def test_generic_ai_placeholder_gates(self):
        config = {"channel": "email", "body": "{{ai_output}}"}
        assert classify_email_content(config, _AI_GRAPH) == "ai"

    def test_source_node_id_referencing_non_ai_node_is_deterministic(self):
        config = {"channel": "email", "body": "x", "source_node_id": "message"}
        assert classify_email_content(config, _AI_GRAPH) == "deterministic"
