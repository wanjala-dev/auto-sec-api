"""The ToolResult contract: a tool returning a ToolResult is serialized to a str.

Pins the framework behaviour the ``ToolResult`` docstring promises — without it a tool
returning a ``ToolResult`` leaked a raw dataclass ``repr`` to the LLM (and tripped the
tool-smoke ``isinstance(result, str)`` guard). Regression guard for ``_serialize_tool_result``.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.base import ToolResult, _serialize_tool_result

pytestmark = [pytest.mark.unit]


def test_toolresult_return_is_serialized_to_str():
    wrapped = _serialize_tool_result(lambda _in="": ToolResult(message="Top sources", data={"n": 3}))
    out = wrapped("{}")
    assert isinstance(out, str)
    assert "Top sources" in out and "3" in out


def test_error_toolresult_serializes_to_error_string():
    wrapped = _serialize_tool_result(lambda _in="": ToolResult(ok=False, error="Missing 'metric'."))
    out = wrapped("{}")
    assert isinstance(out, str)
    assert out.startswith("Error:") and "metric" in out


def test_plain_string_return_passes_through_unchanged():
    wrapped = _serialize_tool_result(lambda _in="": "already a string")
    assert wrapped("{}") == "already a string"
