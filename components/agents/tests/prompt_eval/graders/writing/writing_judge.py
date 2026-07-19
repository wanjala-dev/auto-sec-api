"""LLM-as-judge for generated writing quality (SEE-173).

Mirrors ``PlannerJudge`` but scores prose axes a nonprofit writing
assistant must nail: warmth, specificity, clarity/CTA, and on-voice
tone. One LLM call per case, multi-axis (cheaper + the axes tell
different stories). Qualitative-before-score ordering is enforced in the
prompt so the model doesn't lazily default every axis to ~6/10.

Returns the shared ``ModelGradeResult`` so the harness + report browser
render writing and planner runs identically.

Failure-safe: any init/invoke/parse failure returns a ``ModelGradeResult``
with the error attached and axes empty, so a flaky judge surfaces in the
report rather than silently corrupting the average.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from components.agents.tests.prompt_eval.graders.model._types import (
    AxisScore,
    ModelGradeResult,
)

logger = logging.getLogger(__name__)

_WRITING_AXES = ("warmth", "specificity", "clarity_cta", "on_voice")

GRADER_SYSTEM_PROMPT = """\
You are a meticulous editor grading a piece of writing drafted by a
nonprofit's AI assistant. You grade FOUR axes. For EACH axis, write the
strengths and weaknesses FIRST, then the 0–10 score (writing the score
first makes you lazy — do not).

Axes:
- "warmth": Does it sound like a real, grateful human from this org —
  warm, direct, active voice — not corporate filler or AI boilerplate?
- "specificity": Does it use the concrete facts provided (names, amounts,
  programs, the period) rather than vague platitudes? Anchor each point
  to the supplied facts.
- "clarity_cta": Is it clear, well-structured, and does it end with a
  single clear next step / call-to-action appropriate to the kind?
- "on_voice": Does it respect the workspace's voice rules (tone +
  terminology — e.g. say "recipient" not "child" if instructed)?

Scoring rubric (per axis): 10 = excellent; 7–9 = good, minor gaps; 4–6 =
noticeable gap; 1–3 = poor/misleading; 0 = empty or unusable.

You are scoring STYLE and SUBSTANCE — do NOT verify numeric facts (a
separate deterministic checker does that). Reply with ONLY a JSON object:

{
  "warmth": {"strengths": [..], "weaknesses": [..], "reasoning": "..", "score": 0-10},
  "specificity": {"strengths": [..], "weaknesses": [..], "reasoning": "..", "score": 0-10},
  "clarity_cta": {"strengths": [..], "weaknesses": [..], "reasoning": "..", "score": 0-10},
  "on_voice": {"strengths": [..], "weaknesses": [..], "reasoning": "..", "score": 0-10}
}
"""


class WritingJudge:
    """LLM-as-judge for writing output — 4-axis multi-grader in one call."""

    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        provider: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._provider = provider

    def __call__(
        self,
        case: dict[str, Any],
        draft_payload: dict[str, Any],
    ) -> ModelGradeResult:
        from components.knowledge.infrastructure.factories.llms.factory import (
            LLMFactory,
        )

        context = case.get("context") or {}
        user_payload = json.dumps(
            {
                "kind": context.get("kind") or case.get("kind") or "",
                "goal": case.get("goal", ""),
                "criteria": case.get("criteria", ""),
                "facts_provided": context.get("retrieved_context") or [],
                "voice_rules": context.get("voice") or {},
                "draft_title": draft_payload.get("title", ""),
                "draft_body_html": draft_payload.get("body_html", ""),
            },
            default=str,
        )

        try:
            llm = LLMFactory.get_llm(
                model_name=self._model_name,
                provider=self._provider,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("WritingJudge LLMFactory.get_llm failed: %s", exc)
            return ModelGradeResult(error=f"grader-llm-init-failed: {exc!s}")

        messages = [
            SystemMessage(content=GRADER_SYSTEM_PROMPT),
            HumanMessage(content=user_payload),
        ]
        try:
            raw = llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001
            logger.warning("WritingJudge LLM.invoke failed: %s", exc)
            return ModelGradeResult(error=f"grader-invoke-failed: {exc!s}")

        text = (getattr(raw, "content", "") or "").strip()
        parsed = _parse_judge_json(text)
        if parsed is None:
            return ModelGradeResult(raw_response=text, error="grader-output-not-json")
        return ModelGradeResult(axes=_parse_axes(parsed), raw_response=text, error="")


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_judge_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = _FENCED_JSON_RE.search(text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _parse_axes(payload: dict[str, Any]) -> dict[str, AxisScore]:
    axes: dict[str, AxisScore] = {}
    for name in _WRITING_AXES:
        section = payload.get(name)
        if not isinstance(section, dict):
            continue
        try:
            score = max(0, min(10, int(section.get("score", 0))))
        except (TypeError, ValueError):
            continue
        axes[name] = AxisScore(
            score=score,
            strengths=_coerce_string_list(section.get("strengths")),
            weaknesses=_coerce_string_list(section.get("weaknesses")),
            reasoning=str(section.get("reasoning") or "").strip(),
        )
    return axes


def _coerce_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


DEFAULT_WRITING_JUDGE = WritingJudge()

__all__ = ["WritingJudge", "DEFAULT_WRITING_JUDGE", "GRADER_SYSTEM_PROMPT"]
