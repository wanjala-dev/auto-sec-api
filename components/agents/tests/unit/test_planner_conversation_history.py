"""The planner must serialize conversation_history into the LLM prompt.

PR #78 added ``conversation_history`` to ``DeepPlanAndRunCommand.extra_context``
so follow-up turns ("who is assigned to those 4 tasks?") can resolve
references back to earlier messages. The integration test
(``test_agent_chat_conversation_history.py``) verified the use case
SETS the field, but no test verified the planner actually USES it —
that the messages reach the LLM via the system or human prompt.

This test closes that loop. It uses ``RecordingMockLLM`` to capture
every message the planner sends, then asserts the conversation_history
content is reachable in the prompt the LLM sees.

Without this test, a future refactor could silently drop history
threading and the chat would regress to stateless turns again — the
exact failure shape of the 2026-05-08 cascade.
"""
from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep import llm_planner
from components.agents.tests._helpers.routing_mock_llm import RecordingMockLLM


def _patch_planner_llm(monkeypatch, mock_llm) -> None:
    monkeypatch.setattr(
        "components.knowledge.infrastructure.factories.llms.factory.LLMFactory.get_llm",
        lambda **_: mock_llm,
    )


def test_conversation_history_is_serialized_into_prompt(monkeypatch):
    """Prior turns must reach the LLM as part of the messages.

    Whether the planner serializes history into the system message,
    the human message, or a separate context payload is implementation
    detail — the test asserts the *content* shows up somewhere in the
    captured messages so the LLM can actually use it for reference
    resolution.
    """
    mock = RecordingMockLLM(
        content='{"tasks": [{"title": "stub", "agent_type": "task_agent", "priority": "medium", "status": "todo"}]}'
    )
    _patch_planner_llm(monkeypatch, mock)

    history = [
        {"role": "human", "content": "how many tasks do we have?"},
        {"role": "assistant", "content": "you have 4 todo tasks: A, B, C, D"},
    ]
    llm_planner.plan_with_llm(
        goal="who is assigned to those 4 tasks?",
        plan_id="t-1",
        workspace_id="ws-test",
        extra_context={"conversation_history": history},
    )

    assert mock.invocations, "Planner did not invoke the LLM."
    captured = mock.all_message_contents()

    # Both history entries must be reachable in the prompt the LLM sees.
    assert "how many tasks do we have" in captured, (
        "Prior user turn missing from planner prompt — without this the "
        "LLM cannot resolve 'those 4 tasks' on a follow-up. This is the "
        "exact failure shape from 2026-05-08."
    )
    assert "4 todo tasks: A, B, C, D" in captured, (
        "Prior assistant turn (with the answer) missing from planner "
        "prompt — the LLM needs both sides of the exchange to resolve "
        "anaphoric references like 'those tasks'."
    )

    # The current goal MUST also be present (it's the actual user request,
    # not history). Together: the LLM sees the goal AND the context.
    assert "who is assigned to those 4 tasks?" in captured


def test_first_turn_does_not_inject_phantom_history(monkeypatch):
    """When extra_context is None, the planner must not fabricate history.

    Pinning this catches a class of bug where someone adds defaults like
    ``extra_context = extra_context or {"conversation_history": [...]}``
    and pollutes first-turn prompts with stale data.
    """
    mock = RecordingMockLLM(
        content='{"tasks": [{"title": "stub", "agent_type": "workspace_agent", "priority": "medium", "status": "todo"}]}'
    )
    _patch_planner_llm(monkeypatch, mock)

    llm_planner.plan_with_llm(
        goal="hello",
        plan_id="t-1",
        workspace_id="ws-test",
        extra_context=None,
    )

    assert mock.invocations, "Planner did not invoke the LLM."
    captured = mock.all_message_contents()

    # Common phantom-history sentinels — if these show up on a first turn
    # someone introduced a default history payload by accident.
    assert "previous turn" not in captured.lower()
    assert "conversation history" not in captured.lower() or (
        # The system prompt may mention "conversation history" as a
        # general instruction; that's fine. What we forbid is sample
        # history content like canned Q&A.
        "you have 4 todo tasks" not in captured
    )


def test_empty_history_list_is_indistinguishable_from_no_history(monkeypatch):
    """``conversation_history=[]`` must behave like first-turn.

    The use case sets ``extra_context=None`` when history is empty so
    this case shouldn't normally arise; if it does (edge case where the
    list is built but stays empty), the prompt must still be clean —
    no fabricated turn content sneaks in.

    We compare the user-message JSON specifically, not the whole prompt:
    the system prompt legitimately contains example text ("you have 4
    todo tasks") as routing instruction, which is fine. What we check
    is that the dynamic user payload doesn't carry phantom turns.
    """
    import json

    # Run twice: once with ``extra_context=None``, once with
    # ``extra_context={"conversation_history": []}``. Compare the user
    # messages — they should carry the same conversation_history shape
    # (either absent or empty), never fabricated.
    def capture_user_payload(extra_context):
        mock = RecordingMockLLM(
            content='{"tasks": [{"title": "stub", "agent_type": "workspace_agent", "priority": "medium", "status": "todo"}]}'
        )
        _patch_planner_llm(monkeypatch, mock)
        llm_planner.plan_with_llm(
            goal="hello",
            plan_id="t-1",
            workspace_id="ws-test",
            extra_context=extra_context,
        )
        # The planner sends the user payload as JSON in the human message.
        for messages in mock.invocations:
            for msg in messages:
                content = getattr(msg, "content", None)
                if not isinstance(content, str):
                    continue
                try:
                    payload = json.loads(content)
                except (TypeError, ValueError):
                    continue
                if isinstance(payload, dict) and "goal" in payload:
                    return payload
        raise AssertionError("Planner did not emit a user JSON payload")

    none_payload = capture_user_payload(None)
    empty_payload = capture_user_payload({"conversation_history": []})

    # Neither payload may surface a non-empty conversation_history.
    none_history = (none_payload.get("context") or {}).get(
        "conversation_history", []
    )
    empty_history = (empty_payload.get("context") or {}).get(
        "conversation_history", []
    )

    assert none_history == [], (
        "First-turn (extra_context=None) leaked a non-empty "
        f"conversation_history into the user payload: {none_history}"
    )
    assert empty_history == [], (
        "Empty history (extra_context={'conversation_history': []}) "
        f"leaked turn content: {empty_history}"
    )
