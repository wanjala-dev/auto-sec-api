"""Unit tests for the universal ``retrieve_workspace_context`` tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from components.knowledge.application.ports.vector_store_port import RetrievedChunk


class _FakeAgent:
    """Minimal stand-in for ``BaseAgent`` — only needs workspace_id."""

    def __init__(self, workspace_id: str = "ws-1"):
        self.workspace_id = workspace_id


def _build_tool(workspace_id: str = "ws-1"):
    from components.agents.infrastructure.adapters.langchain.base import BaseAgent

    return BaseAgent._build_workspace_retrieval_tool(_FakeAgent(workspace_id))


class TestRetrieveWorkspaceContextTool:
    def test_empty_query_returns_helpful_message(self):
        tool = _build_tool()
        assert "non-empty query" in tool.func("   ")

    def test_empty_result_returns_honest_no_context_message(self):
        tool = _build_tool()
        fake_port = MagicMock()
        fake_port.search.return_value = []
        with patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ):
            result = tool.func("tldr")
        assert "no indexed context" in result.lower()
        fake_port.search.assert_called_once()

    def test_formats_chunks_with_section_titles(self):
        tool = _build_tool()
        fake_port = MagicMock()
        fake_port.search.return_value = [
            RetrievedChunk(
                content="Name: Wanjala Foundation\nSector: Nonprofit",
                metadata={"section_title": "Workspace identity"},
                score=0.9,
            ),
            RetrievedChunk(
                content="We fund literacy programs.",
                metadata={"section_title": "Mission & story"},
                score=0.8,
            ),
        ]
        with patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ):
            result = tool.func("what is this workspace")

        assert "[1]" in result and "[2]" in result
        assert "Workspace identity" in result
        assert "Mission & story" in result
        assert "Wanjala Foundation" in result

    def test_backend_error_is_swallowed_with_message(self):
        tool = _build_tool()
        fake_port = MagicMock()
        fake_port.search.side_effect = RuntimeError("pg down")
        with patch(
            "components.knowledge.application.providers."
            "workspace_retrieval_provider.workspace_retrieval",
            return_value=fake_port,
        ):
            result = tool.func("mission")
        assert "retrieval backend" in result.lower()

    def test_tool_description_requires_retrieval_before_answering(self):
        tool = _build_tool()
        description = tool.description.lower()
        assert "always call" in description
        assert "do not guess" in description
