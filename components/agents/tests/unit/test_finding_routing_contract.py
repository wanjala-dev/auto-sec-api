"""The anti-strand guard: a routable finding must reach a REAL specialist.

Why this file exists — a real incident. The SAST pillar's P1-era card builder
stamped ``agent_type="ai_teammate"``, which the finding router's non-specialist set
deliberately skips. ``ai.code_security`` WAS in ``ROUTABLE_SOURCE_TYPES``, so the
cards looked routed, but nothing ever dispatched: 15 findings sat invisible to
triage forever, with no error anywhere. Current code stamps ``code_security_agent``
correctly and the stranded cards were backfilled — this test makes that class of
silent strand impossible to reintroduce.

The check is a fitness function over the two halves of the contract:
  * the WRITE half — every ``_SOURCE_BOARD`` builder's ``agent_type``;
  * the ROUTE half — ``ROUTABLE_SOURCE_TYPES`` + ``NON_SPECIALIST_AGENT_TYPES``.
A source that is routable must build cards naming an agent the registry can
actually instantiate. "Routable without a real specialist" is a silent no-op.
"""

from __future__ import annotations

import types

import pytest

from components.agents.application.handlers.finding_raised_board_handler import _SOURCE_BOARD
from components.agents.infrastructure.adapters.langchain.agents import discover_agents
from components.agents.infrastructure.adapters.langchain.base import AgentRegistry
from components.shared_kernel.domain.triage import (
    NON_SPECIALIST_AGENT_TYPES,
    ROUTABLE_SOURCE_TYPES,
    is_routable_to_specialist,
)

pytestmark = pytest.mark.unit


def _fake_finding():
    """A finding shaped like the SSOT entity every card builder reads."""
    return types.SimpleNamespace(
        id="00000000-0000-0000-0000-0000000000ff",
        title="Example finding",
        description="Example description",
        remediation="Do the thing",
        compliance={},
        fingerprint="fp-1",
        severity=types.SimpleNamespace(value="high"),
        attributes={
            "account_id": "123456789012",
            "check_id": "check.1",
            "resource_uid": "arn:aws:s3:::bucket",
            "region": "us-east-1",
            "rule_id": "python.lang.security.example",
            "path": "app/views.py",
            "start_line": 10,
            "end_line": 12,
            "repo": "org/repo",
            "commit_sha": "abcdef1234567890",
            "vulnerability_id": "CVE-2026-0001",
            "pkg_name": "requests",
        },
    )


def _build_card(source: str, mapping: dict) -> dict:
    event = types.SimpleNamespace(
        workspace_id="00000000-0000-0000-0000-00000000000a",
        finding_id="00000000-0000-0000-0000-0000000000ff",
        source=source,
    )
    return mapping["build"](_fake_finding(), event, mapping)


def test_every_routable_board_source_names_a_real_specialist():
    """A routable source's cards must name an agent the registry can instantiate.

    This is the assertion that would have caught the 15 stranded ``ai.code_security``
    cards at build time instead of in production.
    """
    discover_agents()
    registered = {name.lower() for name in AgentRegistry.list_agents()}
    assert registered, "agent registry is empty — discovery did not run"

    problems: list[str] = []
    for source, mapping in _SOURCE_BOARD.items():
        if mapping["source_type"] not in ROUTABLE_SOURCE_TYPES:
            continue
        agent_type = (_build_card(source, mapping).get("agent_type") or "").strip()
        if agent_type in NON_SPECIALIST_AGENT_TYPES:
            problems.append(
                f"{source} → source_type '{mapping['source_type']}' is ROUTABLE but its card stamps "
                f"agent_type='{agent_type}', which the router skips as a non-specialist. Those findings "
                f"would be filed on the board and NEVER triaged, silently."
            )
            continue
        canonical = AgentRegistry.canonical_name_for(agent_type)
        if (canonical or "").lower() not in registered and agent_type.lower() not in registered:
            problems.append(
                f"{source} → card stamps agent_type='{agent_type}', which is not a registered agent. "
                f"The dispatch would fail to resolve a specialist."
            )

    assert not problems, "Stranded finding sources (routable, but nothing will ever triage them):\n" + "\n".join(
        f"  - {p}" for p in problems
    )


def test_non_routable_board_sources_are_deliberate_not_accidents():
    """A source left OUT of the routable set must not name a specialist.

    The inverse strand: a card that names a real specialist but whose source_type is
    not routable would also never be dispatched. Sources meant for human
    investigation (cloud posture, planted instructions) correctly name the
    orchestrator instead.
    """
    discover_agents()
    problems = []
    for source, mapping in _SOURCE_BOARD.items():
        if mapping["source_type"] in ROUTABLE_SOURCE_TYPES:
            continue
        agent_type = (_build_card(source, mapping).get("agent_type") or "").strip()
        if agent_type not in NON_SPECIALIST_AGENT_TYPES:
            problems.append(
                f"{source} → card routes to specialist '{agent_type}' but its source_type "
                f"'{mapping['source_type']}' is not in ROUTABLE_SOURCE_TYPES, so no dispatch reaches it."
            )
    assert not problems, "\n".join(problems)


def test_code_security_is_routed_to_its_specialist():
    """Regression lock for the exact incident: SAST cards name the SAST specialist."""
    card = _build_card("code_security.opengrep", _SOURCE_BOARD["code_security.opengrep"])
    assert card["agent_type"] == "code_security_agent"
    assert is_routable_to_specialist(card["source_type"], card["agent_type"])


@pytest.mark.parametrize(
    ("source_type", "agent_type", "expected"),
    [
        ("ai.code_security", "code_security_agent", True),
        ("ai.log_watch", "triage_agent", True),
        # The exact stranding shape: routable source, orchestrator agent_type.
        ("ai.code_security", "ai_teammate", False),
        ("ai.code_security", "", False),
        # Operator-reading sources are not routable however they are stamped.
        ("ai.cloud_posture", "triage_agent", False),
        ("ai.planted_instructions", "ai_teammate", False),
    ],
)
def test_is_routable_to_specialist(source_type, agent_type, expected):
    assert is_routable_to_specialist(source_type, agent_type) is expected
