"""Reusable prompt-hygiene rules.

The five rules from the LogSeq Anthropic curriculum
(`~/Documents/journals/2026_04_24.md`,
`~/Documents/journals/2026_02_24.md` item 16):

1. No ALL-CAPS urgency markers ≥4 chars (`CRITICAL`, `MUST`, `NEVER`, ...)
   — modern frontier models read these as panic and overtrigger.
2. No anti-pattern phrasing (`Do NOT`, `MUST NOT`, `HARD REQUIREMENT`)
   — causes the model to fixate on the forbidden behaviour.
3. No fallback-route phrases (`if in doubt`, `fallback to`)
   — causes the default path to overtrigger and fabricate.
4. Every routing rule has a `because:` clause
   — models generalise better from explanations than from raw rules.
5. JSON-emitting prompts include a literal `{"...` example block
   — concrete shapes are more imitable than prose descriptions.

These rules live here (not inline in the test) so they can be re-used
by:
- ``test_prompt_hygiene.py`` — the unit-test regression guardrail.
- A future ``manage.py check_prompt_hygiene`` CLI helper.
- A pre-commit hook that runs the rule set against staged prompt
  diffs without spinning up pytest.
- Any new bounded-context test suite that adds its own prompts.

Plan reference: ``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``
Wave 1, step 1F.
"""
from __future__ import annotations

import re

__all__ = [
    "ALL_CAPS_TECHNICAL_WHITELIST",
    "ANTI_PATTERN_PHRASES",
    "FALLBACK_PHRASES",
    "all_caps_offenders",
    "anti_pattern_offenders",
    "fallback_phrase_offenders",
    "routing_rules_missing_because",
    "expects_json",
    "has_json_example_block",
]


# Technical tokens that legitimately appear in ALL-CAPS in a prompt.
# Anything in this set is allowed to stay capitalised; everything else
# is flagged as an urgency marker by ``all_caps_offenders``.
ALL_CAPS_TECHNICAL_WHITELIST: frozenset[str] = frozenset({
    "JSON",
    "USD",
    "UTC",
    "URL",
    "URI",
    "API",
    "RAG",
    "CSV",
    "LLM",
    "ID",
    "UUID",
    "PR",
    "SLA",
    "UI",
    "UX",
    "ISO",
    "PII",
    "OK",
    "TLDR",
    # ``NOT`` is allowed when used as a routing-clarifier between two
    # named agents (e.g. ``task_agent, NOT workspace_agent``). It is
    # only 3 characters so the ``\b[A-Z]{4,}\b`` regex below would not
    # catch it anyway; listing it here documents the intent.
    "NOT",
    # Single-character markers used in examples.
    "X",
    "Y",
    "Z",
    "A",
    "B",
    "C",
    "D",
})


# Phrases the curriculum identifies as anti-patterns. These are
# checked case-sensitively because the harm comes from the urgency the
# capitalisation conveys, not from the words themselves.
ANTI_PATTERN_PHRASES: tuple[str, ...] = (
    "HARD REQUIREMENT",
    "Do NOT",
    "MUST NOT",
    "DO NOT",
    "if in doubt",
)


# Phrases the curriculum flags as fallback-route triggers — they cause
# the model to invoke a default path even when the goal does not match.
FALLBACK_PHRASES: tuple[str, ...] = (
    "if in doubt",
    "fallback to",
)


_ALL_CAPS_WORD_RE = re.compile(r"\b[A-Z]{4,}\b")


def all_caps_offenders(prompt: str) -> list[str]:
    """Return ALL-CAPS standalone words of 4+ chars not in the whitelist.

    Empty list means the prompt passes the rule.
    """
    return [
        word
        for word in _ALL_CAPS_WORD_RE.findall(prompt)
        if word not in ALL_CAPS_TECHNICAL_WHITELIST
    ]


def anti_pattern_offenders(prompt: str) -> list[str]:
    """Return anti-pattern phrases present in the prompt.

    Empty list means the prompt passes the rule.
    """
    return [phrase for phrase in ANTI_PATTERN_PHRASES if phrase in prompt]


def fallback_phrase_offenders(prompt: str) -> list[str]:
    """Return fallback-route phrases present in the prompt (case-insensitive).

    Empty list means the prompt passes the rule.
    """
    lowered = prompt.lower()
    return [phrase for phrase in FALLBACK_PHRASES if phrase in lowered]


def routing_rules_missing_because(prompt: str) -> list[str]:
    """Return routing-rule lines that lack a ``because:`` clause.

    A routing rule, in the planner system prompt, is a nested bullet
    that starts with ``*`` (the catalog list, the carve-out paragraph
    and ordinary contextual notes use ``-``). It also names a
    specialist by the ``_agent`` suffix. Filtering on both keeps the
    check focused on the routing table itself, not on the runtime-
    substituted catalog or the team-membership carve-out.

    Empty list means every routing rule is grounded with a ``because:``
    clause (or there are no routing rules in this prompt, which is
    also fine — e.g. the estimator prompt has none).
    """
    missing: list[str] = []
    for line in prompt.splitlines():
        stripped = line.lstrip()
        if not stripped:
            continue
        if not stripped.startswith("*"):
            continue
        if "_agent" not in stripped:
            continue
        if "because:" not in stripped.lower():
            missing.append(
                stripped[:80] + ("…" if len(stripped) > 80 else "")
            )
    return missing


def expects_json(prompt: str) -> bool:
    """Heuristic: does the prompt instruct the model to emit JSON?

    True if the prompt mentions JSON and pairs it with an output-format
    cue (``only JSON``, ``respond with``, ``output format``).
    """
    lowered = prompt.lower()
    return "json" in lowered and any(
        cue in lowered for cue in ("only json", "respond with", "output format")
    )


def has_json_example_block(prompt: str) -> bool:
    """Return True if the prompt contains a literal JSON example block.

    Templates that use ``str.format()`` escape the braces (``{{`` /
    ``}}``); the resolved prompt unescapes them, so we test ``{"`` and
    ``{ "`` directly.
    """
    return '{"' in prompt or '{ "' in prompt
