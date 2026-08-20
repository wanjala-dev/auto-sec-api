"""The ToolResult contract: content for the model, outcome for the framework.

Pins the framework behaviour the ``ToolResult`` docstring promises — without it a tool
returning a ``ToolResult`` leaked a raw dataclass ``repr`` to the LLM (and tripped the
tool-smoke ``isinstance(result, str)`` guard). Regression guard for ``_serialize_tool_result``.

ADR 0031 D2 made the wrapper return ``(content, artifact)``: ``content`` is the
same string it always was, and ``artifact`` carries the structured outcome that
used to be destroyed here. Both halves are pinned below — the content because
those are the bytes the model reads, the artifact because recovering it is the
whole point of D2.
"""

from __future__ import annotations

import pytest

from components.agents.application.policies.tool_spec import (
    Failure,
    ToolOutcome,
    read_outcome_artifact,
)
from components.agents.infrastructure.adapters.langchain.base import (
    ToolResult,
    _serialize_tool_result,
    _ToolRefusal,
)

pytestmark = [pytest.mark.unit]


def _content(raw):
    content, _artifact = raw
    return content


def _outcome(raw):
    _content_, artifact = raw
    return read_outcome_artifact(artifact)


# ── The model-facing half: unchanged ────────────────────────────────────────


def test_toolresult_return_is_serialized_to_str():
    wrapped = _serialize_tool_result(lambda _in="": ToolResult(message="Top sources", data={"n": 3}))
    out = _content(wrapped("{}"))
    assert isinstance(out, str)
    assert "Top sources" in out and "3" in out


def test_error_toolresult_serializes_to_error_string():
    wrapped = _serialize_tool_result(lambda _in="": ToolResult(ok=False, error="Missing 'metric'."))
    out = _content(wrapped("{}"))
    assert isinstance(out, str)
    assert out.startswith("Error:") and "metric" in out


def test_plain_string_return_passes_through_unchanged():
    wrapped = _serialize_tool_result(lambda _in="": "already a string")
    assert _content(wrapped("{}")) == "already a string"


def test_a_refusal_reaches_the_model_verbatim():
    """``_risk_gated`` returns a ``_ToolRefusal`` rather than a plain ``str`` so
    the framework can classify it. It is a ``str`` subclass precisely so the
    characters the model reads cannot move."""
    refusal = "This action needs approval before it can run."
    wrapped = _serialize_tool_result(lambda _in="": _ToolRefusal(refusal))
    assert _content(wrapped("{}")) == refusal


# ── The out-of-band half: the bit that used to be destroyed ─────────────────


def test_a_successful_result_carries_a_success_outcome():
    wrapped = _serialize_tool_result(lambda _in="": ToolResult(message="fine"))
    envelope = _outcome(wrapped("{}"))
    assert envelope.outcome == ToolOutcome.SUCCESS


def test_a_failed_result_carries_its_reason():
    wrapped = _serialize_tool_result(
        lambda _in="": ToolResult(ok=False, error="gone", failure=Failure.NOT_FOUND, retriable=False)
    )
    envelope = _outcome(wrapped("{}"))
    assert envelope.outcome == ToolOutcome.FAILURE
    assert envelope.failure == Failure.NOT_FOUND
    assert envelope.expected is True


def test_an_unnamed_failure_uses_the_declared_failure_mode():
    wrapped = _serialize_tool_result(
        lambda _in="": ToolResult(ok=False, error="503"),
        Failure.UPSTREAM_UNAVAILABLE,
    )
    assert _outcome(wrapped("{}")).failure == Failure.UPSTREAM_UNAVAILABLE


def test_an_unnamed_failure_with_no_declaration_is_internal():
    """``INTERNAL`` is the loud tier and stays the answer when we genuinely do
    not know — it is just no longer the answer for *everything*."""
    wrapped = _serialize_tool_result(lambda _in="": ToolResult(ok=False, error="???"))
    assert _outcome(wrapped("{}")).failure == Failure.INTERNAL


def test_a_refusal_is_recorded_as_denied():
    wrapped = _serialize_tool_result(lambda _in="": _ToolRefusal("needs approval"))
    envelope = _outcome(wrapped("{}"))
    assert envelope.outcome == ToolOutcome.FAILURE
    assert envelope.failure == Failure.DENIED


def test_a_plain_string_carries_no_outcome_at_all():
    """Most tools return a bare string. "No outcome" is expressed as **no
    artifact**, not as an asserted success — otherwise the framework would be
    manufacturing a success for a tool that reported nothing, which is the
    defect class in miniature. The middleware's last-resort signals then apply.
    """
    wrapped = _serialize_tool_result(lambda _in="": "some rows")
    content, artifact = wrapped("{}")
    assert content == "some rows"
    assert artifact is None
    assert _outcome(wrapped("{}")) is None
