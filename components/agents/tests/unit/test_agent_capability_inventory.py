"""Patterns C + D: per-agent capability inventory + cross-agent overlap.

These tests are the GTM lock for the agent system. They are intentionally
brittle: any change to an agent's tool set without a matching update to
``_helpers/agent_capability_inventory.py`` fails. That is the whole
point — every tool addition becomes a deliberate decision about which
agent owns the verb.

What's covered:

- **Pattern C** — every specialist agent's actual decorated tools must
  match ``CANONICAL_TOOLS[agent_name]`` exactly. Symmetric diff: missing
  tools AND unexpected tools both fail.
- **Pattern D** — no two specialists may register a tool with the same
  name (excluding ``UNIVERSAL_TOOLS`` from the framework). Catches the
  ``create_donation``-on-two-agents class of bug before it ships.

These tests use ``Agent._decorated_tools`` (populated by the ``@tool``
decorator at class-definition time) — no LLM calls, no DB writes, no
agent instantiation. Fast and deterministic.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Set

import pytest

from components.agents.infrastructure.adapters.langchain.base import AgentRegistry
from components.agents.tests._helpers.agent_capability_inventory import (
    CANONICAL_TOOLS,
    UNIVERSAL_TOOLS,
)


# Aliases registered via ``@register_agent("name", aliases=("foo", "bar"))``
# resolve to the same class as the canonical name. We test the canonical
# entry only — testing each alias would exercise the same class N times
# and bury real failures in noise.
_CANONICAL_AGENT_NAMES: Set[str] = set(CANONICAL_TOOLS.keys())


def _decorated_tool_names(agent_class) -> Set[str]:
    """Return the names of every ``@tool``-decorated method on the class.

    Reads ``_decorated_tools`` directly — the list ``BaseAgent.__init_subclass__``
    populates at class-definition time. No instantiation needed, so the
    test stays fast and doesn't require DB / LLM fixtures.
    """
    return {meta.get("name") or method_name for method_name, meta in agent_class._decorated_tools}


class TestPerAgentCapabilityInventory:
    """Pattern C — every agent's tools must match ``CANONICAL_TOOLS`` exactly.

    Missing tool: someone deleted a tool without removing it from the
    inventory. Decide if it's a real removal (delete from inventory) or
    a regression (restore the tool).

    Extra tool: someone added a tool without updating the inventory.
    Decide if it belongs on this agent (add to inventory + add a routing
    keyword in ``ROUTING_EXPECTATIONS``) or another agent.
    """

    @pytest.mark.parametrize("agent_name", sorted(CANONICAL_TOOLS.keys()))
    def test_agent_tools_match_canonical_inventory(self, agent_name):
        agent_class = AgentRegistry.get_agent_class(agent_name)
        assert agent_class is not None, (
            f"Agent {agent_name!r} is in CANONICAL_TOOLS but not registered. "
            "Either register it (via @register_agent) or remove it from "
            "the inventory."
        )

        actual = _decorated_tool_names(agent_class) - UNIVERSAL_TOOLS
        expected = CANONICAL_TOOLS[agent_name]

        missing = expected - actual
        extra = actual - expected

        assert not missing and not extra, (
            f"Agent {agent_name!r} tool inventory drifted.\n"
            f"  MISSING (declared in inventory but not on agent): {sorted(missing)}\n"
            f"  EXTRA (registered on agent but not in inventory): {sorted(extra)}\n"
            "Update components/agents/tests/_helpers/agent_capability_inventory.py "
            "OR fix the agent. The inventory is the contract."
        )

    def test_every_registered_specialist_has_an_inventory_entry(self):
        """No specialist may ship without an inventory entry.

        ``ai_teammate_agent`` is the orchestrator (no tools); skip.
        Aliases (``donation`` for ``donation_agent``, etc.) point at the
        same class as the canonical name — they're not separate
        specialists. We resolve "is this class covered?" by checking
        if ANY of its registered names appears in ``CANONICAL_TOOLS``.
        """
        # Group registered names by class so aliases collapse onto their
        # owning class.
        class_names: Dict[type, Set[str]] = defaultdict(set)
        for name in AgentRegistry.list_agents():
            cls = AgentRegistry.get_agent_class(name)
            if cls is not None:
                class_names[cls].add(name)

        # ``ai_teammate_agent`` is the orchestrator and has no tools by
        # design — its ``_setup_tools`` empties the list.
        orchestrator_aliases = {
            "ai_teammate_agent",
            "ai_teammate",
            "teammate",
            "orchestrator",
        }

        missing_inventory: List[str] = []
        for cls, names in class_names.items():
            if names & orchestrator_aliases:
                continue
            # Class is covered iff any of its registered names matches a
            # canonical inventory key.
            covered = bool(names & _CANONICAL_AGENT_NAMES)
            if not covered:
                # Report by the class's most descriptive name — prefer
                # one ending in ``_agent`` for readability.
                preferred = next(
                    (n for n in sorted(names) if n.endswith("_agent")),
                    sorted(names)[0],
                )
                missing_inventory.append(preferred)

        assert not missing_inventory, (
            f"These registered specialists have no entry in CANONICAL_TOOLS: "
            f"{sorted(missing_inventory)}. Add them to "
            "components/agents/tests/_helpers/agent_capability_inventory.py "
            "with their full tool set, or the planner can route to them "
            "without any test verifying their capability surface."
        )


class TestCrossAgentToolOverlap:
    """Pattern D — no two specialists may claim the same tool name.

    Universal tools (``retrieve_workspace_context``, ``whoami``,
    ``get_workspace_info``) are allow-listed because they're added by
    the framework / mixin to every agent intentionally.

    Anything else appearing on two agents is the ``create_donation``
    class of bug: ambiguous routing destination, depending on which
    agent the planner picks the user gets different behavior.
    """

    # Known overlaps PR-B-1 (boundary cleanup) resolved 2026-05-08:
    # ``create_donation`` (dropped on fundraising_agent — canonical home
    # is donation_agent), ``check_permissions`` (renamed to
    # ``check_financial_permissions`` and ``check_task_permissions``),
    # ``get_project_spend`` (dropped on financial_agent — canonical home
    # is project_agent), ``update_task_status`` (dropped on project_agent
    # — canonical home is task_agent).
    #
    # Empty dict means any collision detected is a real bug. Adding a
    # tool that overlaps with another agent will fail immediately.
    _KNOWN_OVERLAPS_FOR_PR_B: Dict[str, Dict[str, str]] = {}

    def test_no_specialist_overlap_outside_universal_allowlist(self):
        # Build tool_name -> {agent_names} mapping over every registered
        # specialist. Group by class first (so aliases collapse) and
        # report the canonical inventory name when available.
        class_names: Dict[type, Set[str]] = defaultdict(set)
        for name in AgentRegistry.list_agents():
            cls = AgentRegistry.get_agent_class(name)
            if cls is not None:
                class_names[cls].add(name)

        canonical_for_class: Dict[type, str] = {}
        for cls, names in class_names.items():
            inventory_match = names & _CANONICAL_AGENT_NAMES
            if inventory_match:
                canonical_for_class[cls] = next(iter(inventory_match))
            else:
                # No inventory match (orchestrator etc.) — pick any short name.
                canonical_for_class[cls] = sorted(names)[0]

        tool_owners: Dict[str, Set[str]] = defaultdict(set)
        for cls, agent_name in canonical_for_class.items():
            for tool_name in _decorated_tool_names(cls):
                if tool_name in UNIVERSAL_TOOLS:
                    continue
                tool_owners[tool_name].add(agent_name)

        collisions: Dict[str, List[str]] = {
            tool: sorted(agents)
            for tool, agents in tool_owners.items()
            if len(agents) > 1
        }

        # Match against the documented PR-B-resolves set. Any difference —
        # extra tool, missing tool, or different agent set — fires the
        # full assertion below.
        expected_overlap_keys = set(self._KNOWN_OVERLAPS_FOR_PR_B.keys())
        # Only xfail when there ARE collisions AND they exactly match the
        # documented set. Empty collisions = test passes outright (the
        # default for a healthy system).
        if collisions and set(collisions.keys()) == expected_overlap_keys:
            note_lines = [
                "Known overlaps PR-B resolves:",
            ]
            for tool, info in self._KNOWN_OVERLAPS_FOR_PR_B.items():
                note_lines.append(
                    f"  - {tool}: agents=[{info['agents']}] — {info['resolution']}"
                )
            pytest.xfail("\n".join(note_lines))

        assert not collisions, (
            f"These tools are registered on multiple specialists: {collisions}. "
            "Each capability must live on exactly one agent — overlapping "
            "registrations make routing non-deterministic. Either move the "
            "tool to its canonical owner OR add the name to UNIVERSAL_TOOLS "
            "if it's framework-provided. Known overlaps queued for PR-B: "
            f"{sorted(expected_overlap_keys)}."
        )

    def test_canonical_tools_inventory_does_not_double_count_universals(self):
        """Universal tools must NOT appear in any per-agent canonical set.

        If they did, the inventory test would double-fail (universals show
        up on every agent and would be reported as ``EXTRA`` after the
        ``UNIVERSAL_TOOLS`` subtraction). This test guards the inventory
        file itself.
        """
        offenders: Dict[str, Set[str]] = {}
        for agent_name, tools in CANONICAL_TOOLS.items():
            overlap = tools & UNIVERSAL_TOOLS
            if overlap:
                offenders[agent_name] = overlap

        assert not offenders, (
            f"These CANONICAL_TOOLS entries include universal tools that "
            f"are added by the framework: {offenders}. Remove them — the "
            "inventory test subtracts UNIVERSAL_TOOLS before comparing."
        )
