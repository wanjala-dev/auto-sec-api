"""Prompt-hygiene regression test — keeps engineering rules enforced.

Background: the user's Logseq prompt-engineering notes (Anthropic
curriculum, Claude Opus 4.6 lessons that generalise across modern
frontier models) identify several patterns that degrade response
quality:

- ALL-CAPS urgency markers ("CRITICAL", "HARD REQUIREMENT") cause
  overtriggering on newer models.
- Anti-pattern instructions ("Do NOT do X") can cause the model to
  fixate on the forbidden behaviour.
- "If in doubt" / "default to" / "fallback to" instructions cause
  fallback paths to overtrigger and produce fabricated answers.
- Each rule should explain *why* (the model generalises better from
  reasons than from raw rules).
- JSON-emitting prompts should include at least one literal output
  example so the model has a concrete shape to imitate.

This test imports each of the prompts in scope (the planner system
prompt, the project planner, the task planner, the project estimator,
and its repair prompt) and asserts those rules via the shared
``hygiene`` module. A failing assertion means a recent edit
reintroduced one of the patterns the curriculum calls out — fix the
prompt or, if a regression is genuinely justified, update the test
with a comment explaining why.

The reusable rule predicates live in ``components/agents/tests/prompt_eval/hygiene.py``
so they can also be invoked from a CLI helper, a pre-commit hook, or
any future bounded-context test suite that adds its own prompts.

Plan reference: ``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``
Wave 1, step 1F.
"""

from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep import llm_planner
from components.agents.infrastructure.prompts.registry import PromptRegistry
from components.agents.tests.prompt_eval import hygiene
from components.agents.tests.prompt_eval.graders.model import (
    GRADER_SYSTEM_PROMPT,
)

# ---------------------------------------------------------------------------
# Prompts under test
# ---------------------------------------------------------------------------

PROMPTS_UNDER_TEST: dict[str, str] = {
    # The planner template is resolved at runtime so the registered
    # agent catalog is substituted in. Using the resolved version
    # lets the test see what the LLM actually sees.
    "planner.system": llm_planner._build_system_prompt(),
    "planner.project": llm_planner.PROJECT_SYSTEM_PROMPT,
    "planner.task": llm_planner.TASK_SYSTEM_PROMPT,
    # The estimator's runtime module (``tools/project_estimator.py``)
    # was not ported into the auto-sec fork, but its prompts still
    # live in the registry YAMLs — the registry is the single source
    # of truth, so hygiene coverage reads it directly.
    "estimator.system": PromptRegistry.get("estimator.system"),
    "estimator.repair": PromptRegistry.get("estimator.repair"),
    # The LLM-as-judge prompt itself follows the same rules. If we
    # let the judge slip on hygiene, every model-grader score becomes
    # untrustworthy.
    "grader.planner_judge": GRADER_SYSTEM_PROMPT,
}


# ---------------------------------------------------------------------------
# Tests — each one runs against every prompt under test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prompt_id", PROMPTS_UNDER_TEST.keys())
def test_prompt_has_no_all_caps_urgency_markers(prompt_id: str) -> None:
    """ALL-CAPS standalone words (4+ chars) read as urgency on modern models."""
    prompt = PROMPTS_UNDER_TEST[prompt_id]
    offenders = hygiene.all_caps_offenders(prompt)
    assert not offenders, (
        f"Prompt {prompt_id!r} contains ALL-CAPS urgency markers: "
        f"{sorted(set(offenders))}. Per the prompt-engineering rules in the "
        "Logseq curriculum, ALL-CAPS markers like CRITICAL/MUST/NEVER cause "
        "overtriggering on Claude 4.x and modern OpenAI models. Use sentence "
        "case with structural emphasis (lists, headings) instead. If a marker "
        "is a legitimate technical token (e.g., a new acronym), add it to "
        "hygiene.ALL_CAPS_TECHNICAL_WHITELIST."
    )


@pytest.mark.parametrize("prompt_id", PROMPTS_UNDER_TEST.keys())
def test_prompt_has_no_anti_pattern_phrases(prompt_id: str) -> None:
    """No "Do NOT" / "MUST NOT" / "HARD REQUIREMENT" framing.

    The curriculum: only show desired behaviour. Anti-pattern phrases
    can cause the model to fixate on the forbidden behaviour. Express
    the rule positively instead — what the model SHOULD do.
    """
    prompt = PROMPTS_UNDER_TEST[prompt_id]
    found = hygiene.anti_pattern_offenders(prompt)
    assert not found, (
        f"Prompt {prompt_id!r} contains anti-pattern phrasing: {found}. "
        "Rewrite as a positive instruction (what the model SHOULD do). The "
        'exception is a routing carve-out like "task_agent, NOT '
        'workspace_agent", which uses standalone NOT (3 chars) to '
        "disambiguate two named agents — that pattern is allowed. "
        'Phrases like "Do NOT" / "MUST NOT" are not.'
    )


@pytest.mark.parametrize("prompt_id", PROMPTS_UNDER_TEST.keys())
def test_prompt_has_no_fallback_route_instruction(prompt_id: str) -> None:
    """No "if in doubt" or "fallback to" — they overtrigger the default."""
    prompt = PROMPTS_UNDER_TEST[prompt_id]
    found = hygiene.fallback_phrase_offenders(prompt)
    assert not found, (
        f"Prompt {prompt_id!r} contains fallback-route phrasing: {found}. "
        'Per the Logseq prompt rules, "if in doubt" / "default to" / '
        '"fallback to" cause the default path to overtrigger and produce '
        "fabricated answers. Replace with: when the rule does not match, "
        "emit a clarifying task that asks the user to disambiguate."
    )


def test_planner_routing_rules_each_have_a_because_clause() -> None:
    """Each routing rule on the planner system prompt explains why."""
    prompt = PROMPTS_UNDER_TEST["planner.system"]
    missing = hygiene.routing_rules_missing_because(prompt)
    # Sanity: the helper found at least one routing rule. If it found
    # none, the helper that locates them probably needs updating
    # because the prompt structure changed.
    assert hygiene.routing_rules_missing_because(prompt) is not None
    assert not missing, (
        "These planner routing rules lack a `because:` clause:\n  - "
        + "\n  - ".join(missing)
        + "\n\nPer the Logseq rule, models generalise better from "
        "explanations. Add a `because: <reason>` clause to each rule."
    )


@pytest.mark.parametrize(
    "prompt_id",
    [pid for pid, prompt in PROMPTS_UNDER_TEST.items() if hygiene.expects_json(prompt)],
)
def test_json_emitting_prompt_includes_literal_output_example(
    prompt_id: str,
) -> None:
    """Prompts that ask for JSON include at least one literal example block."""
    prompt = PROMPTS_UNDER_TEST[prompt_id]
    assert hygiene.has_json_example_block(prompt), (
        f"Prompt {prompt_id!r} asks for JSON output but contains no "
        "literal example block. Per the Logseq matching-formats rule, "
        "include at least one short worked example so the model has a "
        "concrete output shape to imitate, not just a prose description."
    )


# ---------------------------------------------------------------------------
# Sanity: the prompt set itself is non-empty and every entry is loadable.
# ---------------------------------------------------------------------------


def test_prompts_under_test_are_loaded() -> None:
    """Every prompt in the set actually loaded from its module."""
    for prompt_id, prompt in PROMPTS_UNDER_TEST.items():
        assert isinstance(prompt, str), (
            f"Prompt {prompt_id!r} did not load as a string — the module may have moved or been renamed."
        )
        assert prompt.strip(), f"Prompt {prompt_id!r} is empty or whitespace-only."
