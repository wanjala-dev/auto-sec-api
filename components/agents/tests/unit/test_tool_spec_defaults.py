"""ADR 0031 Phase 1 — the declaration is optional and its defaults change nothing.

The whole migration rests on one promise: **a tool that declares nothing must
behave exactly as it did before ``ToolSpec`` existed.** If that promise is
soft, every one of the 100 undeclared tools is a silent behaviour change and
Phase 1 stops being reversible.

These tests pin the promise at the two places it could break — the ``@tool``
metadata the promotion loop reads, and the risk tier the gate resolves.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_risk import (
    ToolRisk,
    resolve_tool_risk,
)
from components.agents.application.policies.tool_spec import (
    UNDECLARED,
    Failure,
    Provenance,
    Scope,
    ToolSpec,
    build_tool_spec,
    classify_exception,
)
from components.agents.domain.errors import InvalidToolDeclarationError
from components.agents.infrastructure.adapters.langchain.base import tool


class TestUndeclaredToolIsUnchanged:
    def test_tool_without_a_declaration_gets_the_undeclared_singleton(self):
        @tool(name="plain_tool", description="does a thing")
        def plain_tool(self):
            return "ok"

        assert plain_tool._agent_tool_meta["spec"] is UNDECLARED

    def test_undeclared_spec_declares_nothing(self):
        assert UNDECLARED.is_declared is False
        assert UNDECLARED.is_complete is False
        assert UNDECLARED.scope is None
        assert UNDECLARED.risk is None
        assert UNDECLARED.provenance is None
        assert UNDECLARED.failure_mode is None
        assert UNDECLARED.handles == ()
        assert UNDECLARED.as_log_fields() == {}

    def test_pre_adr_metadata_keys_are_byte_identical(self):
        """The promotion loop reads ``name`` / ``description`` / ``args_schema``
        / ``risk``. ADR 0031 may only *add* ``spec`` — changing any of the four
        would change what reaches ``StructuredTool.from_function``."""

        @tool(name="legacy_tool", description="legacy", risk=ToolRisk.IRREVERSIBLE)
        def legacy_tool(self, input_str: str = ""):
            return "ok"

        meta = legacy_tool._agent_tool_meta
        assert meta["name"] == "legacy_tool"
        assert meta["description"] == "legacy"
        assert meta["args_schema"] is None
        assert meta["risk"] == ToolRisk.IRREVERSIBLE
        assert set(meta) == {"name", "description", "args_schema", "risk", "spec"}

    def test_description_still_falls_back_to_the_docstring(self):
        @tool(name="documented")
        def documented(self):
            """The docstring is the description."""

        assert documented._agent_tool_meta["description"] == "The docstring is the description."

    def test_name_still_falls_back_to_the_method_name(self):
        @tool()
        def some_method(self):
            """d"""

        assert some_method._agent_tool_meta["name"] == "some_method"

    @pytest.mark.parametrize("declared_risk", [None, ToolRisk.READ, ToolRisk.IRREVERSIBLE])
    def test_declaring_a_spec_does_not_move_the_risk_gate(self, declared_risk):
        """``resolve_tool_risk`` is what the gate calls. Adding a declaration
        must not change its answer for any tool — the tier still comes from the
        same ``risk`` argument it always did."""

        @tool(name="gated", risk=declared_risk, scope=Scope.WORKSPACE_BOUND)
        def gated(self):
            """d"""

        meta = gated._agent_tool_meta
        assert resolve_tool_risk(meta["name"], meta["risk"]) == resolve_tool_risk("gated", declared_risk)


class TestToolSpecValidation:
    def test_partial_declaration_is_allowed_in_phase_1(self):
        spec = build_tool_spec(scope=Scope.WORKSPACE_FREE)
        assert spec.is_declared is True
        assert spec.is_complete is False
        assert spec.missing_required_fields() == ("risk", "provenance", "failure_mode")

    def test_complete_declaration(self):
        spec = build_tool_spec(
            scope=Scope.WORKSPACE_BOUND,
            risk=ToolRisk.READ,
            provenance=Provenance.NONE,
            failure_mode=Failure.UPSTREAM_UNAVAILABLE,
        )
        assert spec.is_complete is True
        assert spec.missing_required_fields() == ()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"scope": "global"},
            {"provenance": "kanban"},
            {"failure_mode": "boom"},
        ],
    )
    def test_an_unknown_value_is_rejected_at_declaration_time(self, kwargs):
        """Declaration time is class-definition time. A typo in ``scope=``
        fails on import rather than shipping a tool whose governance metadata
        reads correct and means nothing."""
        with pytest.raises(InvalidToolDeclarationError):
            ToolSpec(**kwargs)

    def test_handles_must_be_a_tuple(self):
        with pytest.raises(InvalidToolDeclarationError):
            ToolSpec(handles=["ai.code_security"])

    def test_handles_list_is_normalised_by_the_builder(self):
        assert build_tool_spec(handles=["ai.code_security"]).handles == ("ai.code_security",)

    def test_log_fields_omit_everything_unset(self):
        spec = build_tool_spec(scope=Scope.WORKSPACE_BOUND, handles=("ai.x",))
        assert spec.as_log_fields() == {"scope": Scope.WORKSPACE_BOUND, "handles": ["ai.x"]}


class TestExceptionClassification:
    @pytest.mark.parametrize(
        "exc,expected",
        [
            (ValueError("bad"), Failure.INVALID_INPUT),
            (KeyError("k"), Failure.INVALID_INPUT),
            (PermissionError("no"), Failure.DENIED),
            (ConnectionError("down"), Failure.UPSTREAM_UNAVAILABLE),
            (RuntimeError("?"), Failure.INTERNAL),
        ],
    )
    def test_known_shapes(self, exc, expected):
        assert classify_exception(exc) == expected

    def test_unrecognised_exceptions_stay_loud(self):
        class SomethingNobodyAnticipated(Exception):
            pass

        assert classify_exception(SomethingNobodyAnticipated()) == Failure.INTERNAL
