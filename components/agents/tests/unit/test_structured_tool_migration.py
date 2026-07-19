"""Regression test for the StructuredTool + tool-calling migration.

The 2026-05-08 chat reliability cascade was rooted in two architectural
choices that turned every missing-tool gap into a hallucination:

1. Tools were single-string ``langchain.tools.Tool`` instances → forced
   the agent onto ``create_react_agent``, whose prose parser thrashes
   25 iterations on missing tools and emits the fatal "Agent stopped due
   to iteration limit" stop string.
2. ``agent_chat_use_case`` explicitly set ``use_react_agent=True`` to
   work around that, sealing in the failure mode.

The deep fix is to promote every ``@tool``-decorated method to a
``langchain.tools.StructuredTool`` (typed schema inferred from the
bound method's signature) and let ``BaseAgent._create_agent_executor``
prefer ``create_tool_calling_agent``. With tool-calling, missing
capability returns an honest "I don't have a tool for that" instead of
thrashing into a hallucinated answer.

These assertions lock in both halves of that fix.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from components.agents.application.use_cases import agent_chat_use_case
from components.agents.infrastructure.adapters.langchain.agents.workspace_agent import (
    WorkspaceAgent,
)
from components.agents.infrastructure.adapters.langchain.base import BaseAgent, tool
from components.agents.tests.agent_test_case import AgentTestCase


class StructuredToolMigrationTests(AgentTestCase):
    """The framework promotes ``@tool`` methods to ``StructuredTool``."""

    def test_workspace_agent_tools_are_structured(self):
        agent = self.make_agent(WorkspaceAgent)
        # Every promoted tool MUST be a StructuredTool — that's what
        # gives the tool-calling agent a typed schema to dispatch on.
        # If even one falls back to single-string Tool, the chat path
        # would silently pick ReAct (the tool-calling builder raises
        # "Too many arguments to single-input tool" mid-construction).
        non_structured = [t.name for t in agent.tools if not isinstance(t, StructuredTool)]
        self.assertEqual(
            non_structured,
            [],
            msg=(
                "All workspace_agent tools must be StructuredTool to "
                f"keep the tool-calling path live. Non-structured: "
                f"{non_structured}"
            ),
        )

    def test_universal_retrieval_tool_is_structured(self):
        agent = self.make_agent(WorkspaceAgent)
        retrieval = next(
            (t for t in agent.tools if t.name == "retrieve_workspace_context"),
            None,
        )
        self.assertIsNotNone(
            retrieval,
            msg="retrieve_workspace_context must always be present.",
        )
        self.assertIsInstance(
            retrieval,
            StructuredTool,
            msg=(
                "retrieve_workspace_context must be StructuredTool — "
                "the universal RAG tool is on every agent and would "
                "otherwise force the whole context onto ReAct."
            ),
        )

    def test_decorated_tool_with_args_schema_uses_it(self):
        from pydantic import BaseModel, Field

        class _Schema(BaseModel):
            limit: int = Field(default=10)

        class _StubAgent(BaseAgent):
            profile = {"name": "Stub"}

            @tool(name="list_things", description="List things.", args_schema=_Schema)
            def list_things(self, limit: int = 10) -> str:
                return f"limit={limit}"

        agent = self.make_agent(_StubAgent)
        list_tool = next(t for t in agent.tools if t.name == "list_things")
        self.assertIsInstance(list_tool, StructuredTool)
        # The explicit args_schema must win over signature inference.
        self.assertIs(list_tool.args_schema, _Schema)


class ChatPathDoesNotForceReActTests(AgentTestCase):
    """The chat use case must NOT pin ``use_react_agent=True``.

    Pinning ReAct re-introduces the parser brittleness that caused the
    2026-05-08 cascade. Tool-calling is the production default; ReAct
    stays available as a fallback inside ``BaseAgent`` for models that
    don't advertise function-calling, but chat itself never asks for it.
    """

    def test_chat_use_case_module_does_not_set_use_react_agent_true(self):
        import inspect

        source = inspect.getsource(agent_chat_use_case)
        # Lock in the exact regression. If a future caller ever adds
        # ``use_react_agent=True`` back to this module, this test fires
        # immediately. The fallback path inside BaseAgent is still
        # available — callers that genuinely need ReAct (e.g. a
        # legacy non-function-calling LLM) can opt in via their own
        # agent_config_extra. Chat itself does not.
        self.assertNotIn(
            '"use_react_agent": True',
            source,
            msg=(
                "Chat must not force ReAct. Tool-calling (the new "
                "default) avoids the parser-fragility that caused the "
                "2026-05-08 cascade. See "
                "docs/incidents/2026-05-08-chat-reliability-cascade.md."
            ),
        )


# ── Lenient args adapter regression (PR-I bug A, 2026-05-09) ───────────


class LenientToolInputAdapterTests(AgentTestCase):
    """When a tool method has the legacy single-string signature
    ``def foo(self, input_str: str)`` and the planner LLM passes
    structured kwargs (e.g. ``{"status": "open"}``) instead of
    ``{"input_str": "..."}``, the framework must NOT raise the
    pydantic ``input_str: Field required`` error that surfaced as a
    generic "validation error" in chat. The legacy adapter folds any
    extras into a JSON string and forwards a single string into the
    underlying tool, which already knows how to ``_coerce_payload``
    JSON back to a dict.

    2026-07 fork retune: the original tests drove ``sponsorship_agent.
    list_sponsors`` (the exact tool from the 2026-05-09 wanjala
    incident). That agent was never ported; the contract under test is
    framework behaviour, so the tests now drive it through
    ``triage_agent.list_open_findings`` — a still-legacy
    single-``input_str`` tool on this fork's fleet.
    """

    @staticmethod
    def _list_open_findings_tool(agent):
        return next(t for t in agent.tools if getattr(t, "name", None) == "list_open_findings")

    def test_legacy_tool_accepts_structured_kwargs_from_llm(self):
        """The 2026-05-09 failure shape: the planner invokes a legacy
        single-string tool with structured kwargs and no ``input_str``
        key at all. Pre-fix this raised pydantic ``input_str: Field
        required``; post-fix the call returns the tool's actual
        response string."""
        from components.agents.infrastructure.adapters.langchain.agents.triage_agent import (
            TriageAgent,
        )

        agent = self.make_agent(TriageAgent)
        tool = self._list_open_findings_tool(agent)

        # Invoke through the StructuredTool so pydantic validation runs.
        result = tool.invoke({"status": "open"})

        self.assertIsInstance(result, str)
        self.assertNotIn("validation error", result.lower())
        self.assertNotIn("Field required", result)

    def test_legacy_tool_still_accepts_canonical_input_str_kwarg(self):
        """The fix is additive — tools must still accept the canonical
        ``{"input_str": "..."}`` shape callers may send."""
        from components.agents.infrastructure.adapters.langchain.agents.triage_agent import (
            TriageAgent,
        )

        agent = self.make_agent(TriageAgent)
        tool = self._list_open_findings_tool(agent)

        result = tool.invoke({"input_str": ""})

        self.assertIsInstance(result, str)
        self.assertNotIn("Field required", result)

    def test_legacy_tool_accepts_empty_invocation(self):
        """``tool.invoke({})`` (no args at all) must not crash —
        ``_coerce_payload(None)`` returns ``{}`` in every tool body, so
        an empty dict is the smoke contract Pattern E already locks."""
        from components.agents.infrastructure.adapters.langchain.agents.triage_agent import (
            TriageAgent,
        )

        agent = self.make_agent(TriageAgent)
        tool = self._list_open_findings_tool(agent)

        result = tool.invoke({})

        self.assertIsInstance(result, str)
        self.assertNotIn("Field required", result)
