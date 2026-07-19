"""Deterministic LLM stand-ins for planner-routing tests.

The planner is the only place in the chat path where an LLM gets to decide
``TaskSpec.agent_type`` per task. The 2026-05-08 cascade was caused by the
LLM picking ``workspace_agent`` for "assign those tasks to me" — and we had
no test that would have caught that drift before users hit it.

This module gives tests two deterministic fakes:

* ``RoutingMockLLM(routes)`` — emits canonical plan JSON keyed by goal
  substring. The first matching route's ``agent_type`` is used. If nothing
  matches, returns an empty ``tasks`` list (so retry-logic tests can use
  the same fake).

* ``RecordingMockLLM(content)`` — returns whatever ``content`` you pass
  but captures every ``invoke()`` call's messages on
  ``self.invocations`` so a test can assert what the planner actually
  put in the prompt.

Both implement the minimal LangChain LLM interface the planner uses:
``.invoke(messages: List[BaseMessage]) -> ResponseLike`` where the
response has a ``.content: str`` attribute.

Usage::

    monkeypatch.setattr(
        "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
        lambda **_: RoutingMockLLM({"assign": "task_agent"}),
    )
    plan = plan_with_llm(goal="assign those to me", plan_id="t-1")
    assert plan.tasks[0].agent_type == "task_agent"
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


class _Response:
    """Minimal stand-in for a LangChain LLM ``BaseMessage`` response.

    The planner reads ``response.content``; nothing else. Keeping the
    class concrete (rather than ``MagicMock``) means a typo on
    ``content`` fails loudly instead of returning ``MagicMock()``.
    """

    __slots__ = ("content",)

    def __init__(self, content: str) -> None:
        self.content = content


def _canonical_task(goal: str, agent_type: str) -> Dict[str, Any]:
    """Build a single task dict matching the planner's expected JSON shape.

    Keeps the shape in one place so adding a TaskSpec field doesn't
    require updating every test fixture.
    """
    return {
        "title": goal[:120] if goal else "Answer the user's question",
        "description": goal or "",
        "priority": "medium",
        "status": "todo",
        "agent_type": agent_type,
    }


class RoutingMockLLM:
    """Fake LLM that picks ``agent_type`` by substring-matching the goal.

    Routes are evaluated in insertion order — the first key that appears
    (case-insensitively) as a substring of the human message wins.
    Pass ``default=None`` to emit an empty plan when nothing matches
    (used by the retry-logic test); otherwise the default agent_type is
    used.
    """

    def __init__(
        self,
        routes: Dict[str, str],
        *,
        default: Optional[str] = "workspace_agent",
    ) -> None:
        self.routes = dict(routes)
        self.default = default
        # Each invoke call records (extracted_goal, chosen_agent_type) so
        # tests can assert on what the planner actually saw + decided.
        self.invocations: List[Dict[str, Any]] = []

    def invoke(self, messages: List[Any]) -> _Response:
        goal = self._extract_goal(messages)
        chosen = self._route(goal)
        self.invocations.append({"goal": goal, "chosen": chosen, "messages": list(messages)})

        if chosen is None:
            payload = {"tasks": []}
        else:
            payload = {"tasks": [_canonical_task(goal, chosen)]}
        return _Response(json.dumps(payload))

    def _route(self, goal: str) -> Optional[str]:
        if not goal:
            return self.default
        lowered = goal.lower()
        for keyword, agent_type in self.routes.items():
            if keyword.lower() in lowered:
                return agent_type
        return self.default

    @staticmethod
    def _extract_goal(messages: List[Any]) -> str:
        """Return the goal string the planner sent.

        The planner's user message is a JSON blob ``{"goal": "...", ...}``.
        We pull the ``goal`` field out so tests can match against the
        natural-language goal rather than the wrapped JSON.
        """
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if not isinstance(content, str):
                continue
            try:
                data = json.loads(content)
            except (TypeError, ValueError):
                continue
            if isinstance(data, dict) and "goal" in data:
                return str(data.get("goal") or "")
        # Fallback: last message content as a plain string.
        for msg in reversed(messages):
            content = getattr(msg, "content", None)
            if isinstance(content, str):
                return content
        return ""


class RecordingMockLLM:
    """Fake LLM that captures every ``invoke()`` call for prompt inspection.

    Useful when a test needs to assert what the planner actually put in
    the system / human messages — e.g. that ``conversation_history``
    from ``extra_context`` was serialized into the prompt.
    """

    def __init__(self, content: str = '{"tasks": []}') -> None:
        self.content = content
        self.invocations: List[List[Any]] = []

    def invoke(self, messages: List[Any]) -> _Response:
        self.invocations.append(list(messages))
        return _Response(self.content)

    def all_message_contents(self) -> str:
        """Return every captured message's ``content`` joined by newlines.

        Lets tests do ``"how many tasks" in mock.all_message_contents()``
        without caring which message (system vs human) carried it.
        """
        chunks: List[str] = []
        for messages in self.invocations:
            for msg in messages:
                content = getattr(msg, "content", None)
                if isinstance(content, str):
                    chunks.append(content)
        return "\n".join(chunks)


class SequencedMockLLM:
    """Fake LLM that returns canned content from a queue, one per ``invoke()``.

    Drives the retry-logic test: first call returns empty tasks, second
    returns valid tasks. Asserts the planner actually retried.
    """

    def __init__(self, contents: List[str]) -> None:
        self.contents = list(contents)
        self.invocations: List[List[Any]] = []

    def invoke(self, messages: List[Any]) -> _Response:
        self.invocations.append(list(messages))
        if not self.contents:
            raise AssertionError(
                "SequencedMockLLM ran out of canned responses; the planner "
                f"called invoke {len(self.invocations)} times but the "
                "test only queued fewer responses."
            )
        return _Response(self.contents.pop(0))


__all__ = ["RecordingMockLLM", "RoutingMockLLM", "SequencedMockLLM"]
