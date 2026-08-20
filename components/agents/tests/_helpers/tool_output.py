"""What the model actually reads back from a tool — for tests that call ``.func``.

ADR 0031 D2 promotes every decorated tool with
``response_format="content_and_artifact"``: its ``.func`` returns
``(content, artifact)``, where ``content`` is the string the model reads and
``artifact`` is the structured outcome LangChain documents as "not sent to the
model". ``BaseTool.run`` splits that tuple before the model ever sees it.

Tests that reach *under* the framework and call ``tool.func(...)`` directly —
the smoke harness and the scripted ``AgentTestCase`` executor both do — have to
split it too, or their view of a tool's output diverges from the real one and
they start asserting against a shape production never produces.

One helper, used by both, rather than the same three lines in two places.
"""

from __future__ import annotations

from typing import Any


def model_visible_output(tool: Any, raw: Any) -> Any:
    """The half of a tool's raw return that reaches the model.

    Shape-checked as well as flag-checked: a ``.func`` stubbed by
    ``AgentTestCase.mock_tool_returns`` bypasses the promotion wrapper and
    returns the raw preset, which is not a 2-tuple and must pass through.
    """
    if getattr(tool, "response_format", "content") != "content_and_artifact":
        return raw
    if isinstance(raw, tuple) and len(raw) == 2:
        return raw[0]
    return raw


def tool_outcome_artifact(tool: Any, raw: Any) -> Any:
    """The out-of-band outcome half, or ``None`` when the tool carries none."""
    if getattr(tool, "response_format", "content") != "content_and_artifact":
        return None
    if isinstance(raw, tuple) and len(raw) == 2:
        return raw[1]
    return None
