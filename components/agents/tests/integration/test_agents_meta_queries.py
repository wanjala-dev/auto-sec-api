"""Tests for meta query handling in agents."""
import pytest

from components.agents.infrastructure.adapters.langchain.base import BaseAgent


class StubAgent(BaseAgent):
    """Minimal agent used to test meta query handling without LLM setup."""

    def __init__(self):
        pass

    def _setup_tools(self):
        return None


@pytest.mark.parametrize(
    "prompt",
    [
        "Tell me what you do?",
        "what do you do",
        "What can you do?",
    ],
)
def test_meta_query_returns_profile_summary(prompt):
    agent = StubAgent()
    agent.config = {
        "profile": {
            "name": "Test Agent",
            "summary": "Handles test requests.",
            "capabilities": ["Answer questions", "Summarize data"],
            "sample_prompts": ["What can you do?"],
        }
    }

    response = agent._maybe_handle_meta_query(prompt)

    assert response is not None
    assert "Test Agent Overview" in response
    assert "Handles test requests." in response
    assert "- Answer questions" in response
    assert "- Summarize data" in response
