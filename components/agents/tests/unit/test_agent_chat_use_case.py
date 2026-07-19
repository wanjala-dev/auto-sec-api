"""Unit tests for ``AgentChatUseCase`` — the unified chat entry point."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from components.agents.application.commands.agent_chat_command import (
    AgentChatCommand,
    AgentChatFailure,
    AgentChatSuccess,
)
from components.agents.application.commands.deep_run_command import (
    DeepRunFailure,
    DeepRunSuccess,
)
from components.agents.application.use_cases.agent_chat_use_case import (
    AgentChatUseCase,
    _extract_final_answer,
)


def _command(**overrides) -> AgentChatCommand:
    defaults = dict(
        query="tldr this workspace",
        workspace_id=uuid4(),
        user_id=uuid4(),
        agent_type="workspace_agent",
    )
    defaults.update(overrides)
    return AgentChatCommand(**defaults)


def _ai_config(**overrides):
    """Duck-typed stand-in for the dataclass the real port returns."""
    defaults = dict(
        ai_enabled=True,
        preferred_provider="openai",
        preferred_model="gpt-4o-mini",
        temperature=0.1,
    )
    defaults.update(overrides)
    return type("AIConfig", (), defaults)()


class _FakePolicyDecision:
    def __init__(
        self,
        allowed: bool,
        reason: str = "",
        *,
        is_workspace_quota_exceeded: bool = False,
    ):
        self.is_allowed = allowed
        self.reason = reason
        # Mirrors AIAccessCheckResult.is_workspace_quota_exceeded —
        # the use case branches on this to decide 403 (per-persona /
        # role refusal) vs 429 (workspace-level cap). Per-persona
        # denials default to False.
        self.is_workspace_quota_exceeded = is_workspace_quota_exceeded
        # Fields surfaced into quota_info on 429 responses. Test
        # fake exposes neutral defaults so attribute access never
        # blows up if a future test simulates a workspace-cap path.
        self.decision = "denied" if not allowed else "allowed"
        self.workspace_daily_remaining_messages = -1
        self.workspace_monthly_remaining_tokens = -1


def _build_use_case(
    *,
    deep_result=None,
    entitlement_allows: bool = True,
    ai_enabled: bool = True,
    policy_allows: bool = True,
    policy_reason: str = "",
) -> tuple[AgentChatUseCase, MagicMock, MagicMock]:
    deep = MagicMock()
    deep.execute = MagicMock(return_value=deep_result)

    entitlement = MagicMock()
    entitlement.is_agent_enabled_for_workspace = MagicMock(return_value=entitlement_allows)

    ai_config_port = MagicMock()
    ai_config_port.load = MagicMock(return_value=_ai_config(ai_enabled=ai_enabled))
    ai_config_port.get_messages_used_today = MagicMock(return_value=0)

    use_case = AgentChatUseCase(
        deep_plan_and_run=deep,
        entitlement=entitlement,
        ai_config_port=ai_config_port,
        session_memory=None,
    )

    # Monkey-patch the persona policy on the instance to be deterministic.
    from components.agents.application.use_cases import agent_chat_use_case as mod

    mod._persona_policy.check_feature_access = MagicMock(
        return_value=_FakePolicyDecision(policy_allows, policy_reason)
    )
    mod._persona_policy.check_agent_access = MagicMock(
        return_value=_FakePolicyDecision(policy_allows, policy_reason)
    )
    return use_case, deep, entitlement


class TestExtractFinalAnswer:
    def test_reads_final_output_answer(self):
        state = {"final_output": {"answer": "Wanjala funds literacy."}}
        assert _extract_final_answer(state) == "Wanjala funds literacy."

    def test_falls_back_to_last_completed_task_summary(self):
        state = {
            "completed_tasks": [
                {"summary": "step 1"},
                {"summary": "step 2"},
            ]
        }
        assert _extract_final_answer(state) == "step 2"

    def test_returns_blank_when_nothing_usable(self):
        assert _extract_final_answer({}) == ""
        assert _extract_final_answer({"final_output": {}}) == ""
        assert _extract_final_answer("not a dict") == ""


class TestAgentChatUseCase:
    def test_success_returns_grounded_answer(self):
        deep_result = DeepRunSuccess(
            plan_id="p-1",
            state={"final_output": {"answer": "Wanjala funds literacy."}},
        )
        use_case, deep, entitlement = _build_use_case(deep_result=deep_result)

        result = use_case.execute(_command())

        assert isinstance(result, AgentChatSuccess)
        assert result.response == "Wanjala funds literacy."
        assert result.plan_id == "p-1"
        assert result.source == "deep_agent"
        deep.execute.assert_called_once()
        # chat mode should never sync to kanban
        call_kwargs = deep.execute.call_args
        command = call_kwargs.args[0]
        assert command.sync_to_kanban is False

    def test_ai_disabled_returns_403_failure_without_calling_deep(self):
        use_case, deep, _ = _build_use_case(
            deep_result=DeepRunSuccess(plan_id="x", state={}), ai_enabled=False
        )
        result = use_case.execute(_command())
        assert isinstance(result, AgentChatFailure)
        assert result.status_code == 403
        deep.execute.assert_not_called()

    def test_entitlement_denial_returns_403(self):
        use_case, deep, _ = _build_use_case(
            deep_result=DeepRunSuccess(plan_id="x", state={}),
            entitlement_allows=False,
        )
        result = use_case.execute(_command())
        assert isinstance(result, AgentChatFailure)
        assert result.status_code == 403
        deep.execute.assert_not_called()

    def test_persona_denial_returns_403(self):
        use_case, deep, _ = _build_use_case(
            deep_result=DeepRunSuccess(plan_id="x", state={}),
            policy_allows=False,
            policy_reason="Daily quota exceeded",
        )
        result = use_case.execute(_command())
        assert isinstance(result, AgentChatFailure)
        assert result.status_code == 403
        assert "quota" in result.error.lower()
        deep.execute.assert_not_called()

    def test_deep_run_failure_propagates(self):
        use_case, _, _ = _build_use_case(
            deep_result=DeepRunFailure(error="planner crashed", status_code=500)
        )
        result = use_case.execute(_command())
        assert isinstance(result, AgentChatFailure)
        assert result.status_code == 500
        assert "planner crashed" in result.error

    def test_empty_final_answer_returns_failure(self):
        use_case, _, _ = _build_use_case(
            deep_result=DeepRunSuccess(plan_id="p-2", state={})
        )
        result = use_case.execute(_command())
        assert isinstance(result, AgentChatFailure)
        assert "without producing a response" in result.error

    def test_client_supplied_plan_id_is_used_for_deep_run(self):
        """The chat UI generates a UUID *before* sending the request and
        opens a WebSocket on ``resource.agent_run.<that uuid>``. If the
        use case ignored ``command.plan_id`` and minted a server-side
        UUID instead, the WS subscription would never receive any
        events — the live tool-call card would stay empty. Pin the
        contract so a future revert fails loudly here.
        """
        deep_result = DeepRunSuccess(
            plan_id="client-supplied-plan-id",
            state={"final_output": {"answer": "ok"}},
        )
        use_case, deep, _ = _build_use_case(deep_result=deep_result)

        client_plan = uuid4()
        result = use_case.execute(_command(plan_id=client_plan))

        assert isinstance(result, AgentChatSuccess)
        deep_command = deep.execute.call_args.args[0]
        assert deep_command.plan_id == str(client_plan), (
            "The deep-run command must carry the client-supplied "
            "plan_id verbatim, otherwise the WS subscription opened "
            "by the chat UI lands on the wrong group and shows zero "
            "events."
        )

    def test_no_plan_id_falls_back_to_generated_uuid(self):
        """Older callers (CLI, tests, internal automation) don't supply
        a plan_id. They must keep working — the use case generates one
        and returns it, just at the cost of the WS-subscribes-first
        UX optimisation.
        """
        deep_result = DeepRunSuccess(
            plan_id="server-generated",
            state={"final_output": {"answer": "ok"}},
        )
        use_case, deep, _ = _build_use_case(deep_result=deep_result)

        result = use_case.execute(_command(plan_id=None))

        assert isinstance(result, AgentChatSuccess)
        deep_command = deep.execute.call_args.args[0]
        # A real UUID — not empty, not literally the string "None".
        assert deep_command.plan_id
        assert deep_command.plan_id.lower() != "none"
        # Generated, not echoing whatever the client sent (which was
        # nothing).
        from uuid import UUID as _UUID
        _UUID(deep_command.plan_id)  # raises if not a UUID
