"""Unit tests for ``BaseAgent._persist_tool_observations``.

The helper takes each (AgentAction, observation) pair from
LangChain's ``intermediate_steps`` and writes a ``tool_observation``
DeepRunLog row. The RAG eval harness reads those rows to score
Faithfulness on answers whose evidence came from an ORM-reading
tool (donation_agent, financial_agent) instead of the retrieved
snapshot chunks. The frontend realtime layer also picks the rows
up via the DeepRunLog signal bridge, so getting the persist
contract right matters beyond the eval.

These tests pin the contract end-to-end at the persist layer so a
future refactor of LangChain's intermediate_steps shape or the
gateway can't quietly break either consumer.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from components.agents.infrastructure.adapters.langchain.base import BaseAgent


class _FakeAgent:
    """Stand-in carrying just the surface ``_persist_tool_observations`` reads.

    ``self.__class__.__name__`` flows into the persisted row as
    ``agent_type`` — we leave it as ``_FakeAgent`` rather than
    spoofing because the test asserts on the value, and a real
    subclass-name leak there would be more informative than a
    fixed mock.
    """

    agent_id = "agent-test"
    _TOOL_OBSERVATION_MAX_CHARS = BaseAgent._TOOL_OBSERVATION_MAX_CHARS


def _call(run_context, intermediate_steps):
    return BaseAgent._persist_tool_observations(
        _FakeAgent(),
        run_context,
        intermediate_steps,
    )


class TestPersistToolObservationsGuards:
    def test_no_run_context_no_writes(self):
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(None, [(SimpleNamespace(tool="x", tool_input=""), "out")])
        log.assert_not_called()

    def test_run_context_without_thread_id_no_writes(self):
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call({}, [(SimpleNamespace(tool="x", tool_input=""), "out")])
        log.assert_not_called()

    def test_empty_intermediate_steps_no_writes(self):
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call({"run_id": "thread-1"}, [])
        log.assert_not_called()

    def test_step_with_blank_tool_name_skipped(self):
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(
                {"run_id": "thread-1"},
                [
                    (SimpleNamespace(tool="", tool_input=""), "out"),
                    (SimpleNamespace(tool="real", tool_input="q"), "out2"),
                ],
            )
        # Only the real tool should have been logged.
        assert log.call_count == 1
        kwargs = log.call_args.kwargs
        assert kwargs["tool_name"] == "real"

    def test_malformed_step_does_not_crash_loop(self):
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(
                {"run_id": "thread-1"},
                [
                    "not-a-tuple",
                    (SimpleNamespace(tool="real", tool_input=""), "out"),
                ],
            )
        # The malformed step is skipped; the real one still lands.
        assert log.call_count == 1


class TestPersistToolObservationsPayload:
    def test_writes_one_row_per_intermediate_step(self):
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(
                {"run_id": "thread-42"},
                [
                    (
                        SimpleNamespace(
                            tool="top_donors", tool_input={"limit": 5}
                        ),
                        "Total: $12,500",
                    ),
                    (
                        SimpleNamespace(
                            tool="get_donor_info", tool_input="Jane"
                        ),
                        "Jane gave $250",
                    ),
                ],
            )
        assert log.call_count == 2
        first = log.call_args_list[0]
        assert first.args == ("thread-42", "tool_observation")
        assert first.kwargs["tool_name"] == "top_donors"
        # dict tool_input is JSON-serialised so the payload column
        # stays a string and the websocket consumer reads a stable
        # type.
        assert first.kwargs["payload"]["tool_input"] == '{"limit": 5}'
        assert first.kwargs["payload"]["tool_output"] == "Total: $12,500"
        assert first.kwargs["payload"]["truncated_input"] is False
        assert first.kwargs["payload"]["truncated_output"] is False

    def test_thread_id_falls_back_to_plan_id(self):
        """The deep runner sometimes passes ``plan_id`` instead of
        ``run_id``; the helper must accept either as the thread key
        so it doesn't silently drop rows depending on which key the
        caller used."""
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(
                {"plan_id": "plan-7"},
                [(SimpleNamespace(tool="t", tool_input=""), "x")],
            )
        assert log.call_args.args[0] == "plan-7"

    def test_long_payload_truncated_to_max_chars(self):
        """A tool that returns 100KB of CSV must not blow up the
        JSON column or the websocket envelope. The contract: cap
        each field to ``_TOOL_OBSERVATION_MAX_CHARS`` and set
        ``truncated_*`` so the consumer can label trimmed cells."""
        big_input = "x" * (BaseAgent._TOOL_OBSERVATION_MAX_CHARS + 10)
        big_output = "y" * (BaseAgent._TOOL_OBSERVATION_MAX_CHARS + 99)
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(
                {"run_id": "thread-1"},
                [
                    (
                        SimpleNamespace(tool="bulk", tool_input=big_input),
                        big_output,
                    )
                ],
            )
        payload = log.call_args.kwargs["payload"]
        assert (
            len(payload["tool_input"])
            == BaseAgent._TOOL_OBSERVATION_MAX_CHARS
        )
        assert (
            len(payload["tool_output"])
            == BaseAgent._TOOL_OBSERVATION_MAX_CHARS
        )
        assert payload["truncated_input"] is True
        assert payload["truncated_output"] is True

    def test_none_observation_renders_as_empty_string(self):
        """LangChain agents occasionally return ``None`` as a tool
        observation (e.g. an action with no follow-up). The helper
        must render that as an empty string, not the literal word
        ``None``, so the judge sees clean empty content."""
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(
                {"run_id": "thread-1"},
                [(SimpleNamespace(tool="noop", tool_input=""), None)],
            )
        assert log.call_args.kwargs["payload"]["tool_output"] == ""

    def test_agent_type_is_callers_class_name(self):
        """``agent_type`` carries the *subclass* name so a downstream
        viewer can attribute the row to the right agent (Sponsorship
        vs Donation vs Project). Asserts the lookup uses
        ``self.__class__.__name__`` rather than a hardcoded string."""
        with patch(
            "components.agents.infrastructure.gateways.deep.logging."
            "log_deep_event"
        ) as log:
            _call(
                {"run_id": "thread-1"},
                [(SimpleNamespace(tool="t", tool_input=""), "out")],
            )
        assert log.call_args.kwargs["agent_type"] == "_FakeAgent"
