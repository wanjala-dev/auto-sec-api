"""Fitness function F6 (ADR 0031): every ``_TOOL_RISK`` key names a real tool.

``_TOOL_RISK`` (``components/agents/application/policies/tool_risk.py``) is the
central name→risk-tier map behind ``resolve_tool_risk``, which drives two gates:
the autonomy cap (an autonomous run may never execute an ``irreversible`` tool)
and the human-approval gate. It is the fallback for tools that predate
``@tool(risk=...)``.

When this fork stripped the nonprofit domain it took the tools with it but left
their entries behind. **Eight of the map's ten keys** —
``manage_sponsorship_payments``, ``cancel_sponsorship``,
``cancel_recurring_donation``, ``send_sponsor_update``, ``delete_transaction``,
``delete_news_article``, ``delete_event``, ``delete_estimate`` — named tools no
agent in this codebase has registered since the fork. Nothing failed, because
nothing looked. They read as a considered money-tool policy, and they governed
nothing.

That is the hazard worth a test. A risk map that is 80% fiction is a map nobody
audits line-by-line, and an unaudited risk map is where a *missing* tier hides —
the exact failure ``tool_risk.py``'s own docstring says it exists to prevent
("under-classifying an irreversible money tool as ``read``"). Deleting the eight
was cheap; keeping the map honest from here is what this test buys.

This is the same argument ``test_sole_session_minter.py`` makes: three bad call
sites were each found by hand, one incident at a time, before someone wrote the
rule. Written as a rule, the fourth is found by CI.

**The rule is one-directional on purpose.** It says every key must name a live
tool. It does NOT say every live tool must have a key — 55 of ~100 tools declare
no tier at all and correctly default to ``read``. Closing *that* gap is F1, and
it needs the declaration ADR 0031 D1 and D2 introduce; conflating the two here
would either baseline a real violation or block Phase 0 on Phase 3.

Both tool-name sources are consulted and unioned, because being wrong in the
"this key is dead" direction deletes a live risk tier — a security regression,
not a cleanup bug:

1. **The live registry** — ``AgentRegistry`` + ``_decorated_tools``, populated by
   ``@tool`` at class-definition time. Catches anything registered dynamically.
2. **A static AST scan** of ``components/agents/`` — every ``@tool``-decorated
   method and every ``name=<literal>`` passed to a ``Tool`` / ``StructuredTool``
   constructor. Catches anything the registry misses, and ``discover_agents()``
   swallows a failing agent import (``agents/__init__.py``), so the registry
   alone can silently shrink.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

AGENTS_PACKAGE = ROOT / "components" / "agents"

#: Constructors whose ``name=`` kwarg names a tool the LLM can call.
_TOOL_CONSTRUCTORS = {"Tool", "StructuredTool", "from_function"}


def _tool_names_from_source() -> set[str]:
    """Every tool name derivable from ``components/agents/`` source, statically."""
    names: set[str] = set()
    for path in sorted(AGENTS_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path.relative_to(ROOT)))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names |= _names_from_tool_decorators(node)
            elif isinstance(node, ast.Call):
                names |= _names_from_tool_constructor(node)
    return names


def _names_from_tool_decorators(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """``@tool(name="x")`` → ``{"x"}``; bare ``@tool`` → the method name."""
    for decorator in node.decorator_list:
        func = decorator.func if isinstance(decorator, ast.Call) else decorator
        attr = getattr(func, "id", None) or getattr(func, "attr", None)
        if attr != "tool":
            continue
        if isinstance(decorator, ast.Call):
            for keyword in decorator.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                    return {str(keyword.value.value)}
        return {node.name}
    return set()


def _names_from_tool_constructor(node: ast.Call) -> set[str]:
    """``StructuredTool.from_function(name="x", ...)`` / ``Tool(name="x", ...)``."""
    func = node.func
    attr = getattr(func, "id", None) or getattr(func, "attr", None)
    if attr not in _TOOL_CONSTRUCTORS:
        return set()
    return {
        str(keyword.value.value)
        for keyword in node.keywords
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant)
    }


def _tool_names_from_registry() -> set[str]:
    """Every tool name the live ``AgentRegistry`` exposes.

    Reads ``_decorated_tools`` — the list ``BaseAgent.__init_subclass__`` builds
    at class-definition time — off every registered class. No instantiation, no
    ORM: the architecture conftest blocks DB access and this must stay clean
    under it.
    """
    from components.agents.infrastructure.adapters.langchain.base import AgentRegistry

    names: set[str] = set()
    for agent_name in AgentRegistry.list_agents():
        agent_class = AgentRegistry.get_agent_class(agent_name)
        if agent_class is None:
            continue
        # ``agent_bridge.create_agent_tool`` names its delegation tool after the
        # target agent, so an orchestrator's surface is derived, not written.
        names.add(f"call_{agent_name}")
        for method_name, meta in getattr(agent_class, "_decorated_tools", []):
            names.add(meta.get("name") or method_name)
    return names


def _live_tool_names() -> set[str]:
    return _tool_names_from_source() | _tool_names_from_registry()


def test_every_tool_risk_key_names_a_tool_that_exists():
    from components.agents.application.policies.tool_risk import _TOOL_RISK

    live = _live_tool_names()
    dead = sorted(key for key in _TOOL_RISK if key not in live)

    assert dead == [], (
        "these _TOOL_RISK keys name tools no agent registers, so their tier "
        "governs nothing and the map reads as policy it does not enforce: "
        f"{dead}. If the tool was deleted, delete its entry (this is what "
        "Phase 0 of ADR 0031 did for the eight nonprofit leftovers). If the "
        "tool was renamed, rename the key — tool names are load-bearing "
        "strings (ADR 0031 D8). Do not add an exemption list: an entry that "
        "governs nothing is exactly what this test exists to delete."
    )


def test_the_tool_name_sources_actually_find_tools():
    """A scan that finds nothing would make the rule above vacuously true.

    Both sources are asserted separately: if only one breaks, the union still
    passes F6 and the guard silently degrades to half a check.
    """
    from_source = _tool_names_from_source()
    from_registry = _tool_names_from_registry()

    assert "delete_task" in from_source, (
        "the AST scan found no @tool-decorated `delete_task` under "
        "components/agents/ — the decorator shape changed and this scanner "
        f"needs updating. Found {len(from_source)} names."
    )
    assert "delete_task" in from_registry, (
        "AgentRegistry exposes no `delete_task` — either agent discovery "
        "failed (discover_agents() swallows import errors) or the registry "
        f"shape changed. Found {len(from_registry)} names."
    )
