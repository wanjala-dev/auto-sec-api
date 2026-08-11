"""The rubric contract: every graded agent has checkable criteria.

An agent in ``CRITIC_ENABLED_AGENTS`` with no entry in ``RUBRICS`` is graded on
the generic system prompt alone — "vibes". That is the exact failure mode Huang
et al. (ICLR 2024, "LLMs Cannot Self-Correct Reasoning Yet") documents: pure LLM
self-critique degenerates into a consistency check and can make a correct answer
worse. The agents skill states the rule directly — "Adding a specialist to
CRITIC_ENABLED_AGENTS REQUIRES adding its rubric here" — and prose has already
proven insufficient once this week, so it is a test.

``resolve_rubric_text`` (deep/rubric.py) gates on the SAME set, so a missing
rubric also silently turns RubricMiddleware into a no-op for that agent: enabled
in one place, ungradable in another, with nothing on fire.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep.critic import (
    CRITIC_ENABLED_AGENTS,
    RUBRICS,
)
from components.agents.infrastructure.adapters.langchain.deep.rubric import resolve_rubric_text

pytestmark = pytest.mark.unit


class _Agent:
    """Mirrors how ``_resolve_agent_type`` actually reads the slug: from the
    DB-backed ``config["agent_type"]``, falling back to the class attribute
    ``_canonical_agent_name``. An instance ``.agent_type`` is NOT consulted —
    a stub that sets one silently resolves to "" and every rubric assertion
    passes against ``None``."""

    def __init__(self, agent_type: str) -> None:
        self.config = {"agent_type": agent_type}


class _ClassSlugAgent:
    """The other resolution path — a registered BaseAgent subclass with no
    per-workspace config override."""

    _canonical_agent_name = "code_security_agent"
    config = None


class TestEveryGradedAgentHasARubric:
    def test_no_agent_is_graded_without_criteria(self):
        missing = sorted(CRITIC_ENABLED_AGENTS - set(RUBRICS))
        assert not missing, (
            f"{missing} are graded but have no rubric — they would be scored on the "
            "grader's general impression. Add checkable criteria to RUBRICS, or drop "
            "them from CRITIC_ENABLED_AGENTS."
        )

    def test_no_rubric_is_written_for_an_ungraded_agent(self):
        """The inverse drift: a rubric nobody reads."""
        orphaned = sorted(set(RUBRICS) - CRITIC_ENABLED_AGENTS)
        assert not orphaned, f"{orphaned} have rubrics but are never graded — dead config."

    @pytest.mark.parametrize("agent_type", sorted(CRITIC_ENABLED_AGENTS))
    def test_criteria_are_a_checklist_not_a_paragraph(self, agent_type):
        """Rubrics are enumerated criteria the grader can check one by one."""
        rubric = RUBRICS[agent_type]
        criteria = [line for line in rubric.splitlines() if line.strip().startswith("-")]
        assert len(criteria) >= 3, f"{agent_type} has {len(criteria)} criteria; want a real checklist"
        assert all(len(line.split()) >= 5 for line in criteria), f"{agent_type} has a criterion too terse to check"


class TestCodeSecurityAgentIsGraded:
    """The specialist that produces most draft PRs was in neither loop."""

    def test_it_is_enabled(self):
        assert "code_security_agent" in CRITIC_ENABLED_AGENTS

    def test_its_rubric_reaches_the_middleware(self):
        assert resolve_rubric_text(_Agent("code_security_agent")) == RUBRICS["code_security_agent"]

    def test_it_resolves_from_the_class_slug_too(self):
        """Most runs have no per-workspace config override."""
        assert resolve_rubric_text(_ClassSlugAgent()) == RUBRICS["code_security_agent"]

    def test_an_ungraded_agent_still_resolves_to_none(self):
        """Non-enabled agents run middleware-free-in-effect — unchanged."""
        assert resolve_rubric_text(_Agent("workspace_agent")) is None

    def test_criteria_target_reasoning_not_the_artifact(self):
        """Patch existence/parse/shape are settled deterministically by the ADR 0025
        oracles. A rubric criterion restating them would let an LLM opinion
        contradict a fact — and would leave the real gap (semantic
        misunderstanding, 51.4% of failures) ungraded."""
        rubric = RUBRICS["code_security_agent"].lower()
        assert "snippet" in rubric, "criteria must anchor on the finding's own evidence"
        for artifact_check in ("parses", "syntax error", "compiles"):
            assert artifact_check not in rubric, (
                f"'{artifact_check}' duplicates a deterministic oracle — leave artifact "
                "validity to finding_verifier.py and grade the reasoning here"
            )
