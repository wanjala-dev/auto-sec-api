"""End-to-end smoke test for the migrated BlogAgent (ADR 0003).

Demonstrates the new `AgentTestCase` harness — no real LLM calls, no
real DB writes, fully deterministic. Future agent tests should follow
this template.

Two assertions previously lived here that drifted out of sync with the
agent (the hardcoded tool count check and the profile-name string
check). They were removed 2026-05-08 — the canonical replacement is
``components/agents/tests/unit/test_agent_capability_inventory.py``,
which enforces the EXACT tool set per agent via symmetric diff and
fails immediately when an agent's surface changes without a matching
inventory update. That's stricter than counting names and doesn't
break on user-facing copy edits.
"""

from __future__ import annotations

from components.agents.infrastructure.adapters.langchain.agents.blog_agent import (
    BlogAgent,
)
from components.agents.infrastructure.adapters.langchain.base import AgentRegistry
from components.agents.tests.agent_test_case import AgentTestCase


class BlogAgentDecoratorTests(AgentTestCase):
    def test_registry_resolves_blog_agent(self):
        cls = AgentRegistry.get_agent_class("blog_agent")
        self.assertIs(cls, BlogAgent)
        # Aliases should resolve to the same class.
        self.assertIs(AgentRegistry.get_agent_class("blog"), BlogAgent)
        self.assertIs(AgentRegistry.get_agent_class("news"), BlogAgent)

    def test_tool_call_via_scripted_executor(self):
        self.mock_tool_returns("get_news_articles", "5 active articles")
        self.mock_llm_chooses("get_news_articles", "all")
        agent = self.make_agent(BlogAgent)

        result = agent.agent_executor.invoke({"input": "how many articles"})

        self.assert_tool_called("get_news_articles")
        self.assert_tool_called_with("get_news_articles", "all")
        self.assertIn("5 active articles", result["output"])
