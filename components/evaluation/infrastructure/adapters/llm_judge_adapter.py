"""The judge: an LLM that must reason before it grades (ADR 0033 D6/D10).

Two independent sources converged on the same instruction, from different
directions, so it is treated as a hard requirement rather than a preference:

- the inter-rater literature measured judge agreement rising from kappa ~0.55
  to ~0.75 when the judge writes a rationale first;
- Anthropic's own course material warns that without strengths / weaknesses /
  reasoning "models tend to default to middling scores around 6".

So the schema is ordered ``strengths -> weaknesses -> reasoning -> verdicts``
and the model is told, in those words, to fill it in that order. A judge that
emits its verdict first is anchoring, then rationalising.

The other borrowed instruction is the anti-harshness one, which is the
counter-intuitive half: *grade only against the stated criteria, and a case
meeting all of them passes*. A judge that invents standards makes the agent
look worse than it is. Every other honesty rule in this codebase guards against
over-claiming; this one guards the opposite direction, and it is just as much a
lie.

Verdicts are per-axis booleans, not a 1-10 score (D10): a rate over binary
outcomes is interpretable and Cohen's kappa is defined for it, neither of which
is true of a mean score.
"""

from __future__ import annotations

import json
import logging
import re

from components.evaluation.application.ports.eval_ports import (
    AgentOutcome,
    EvalCaseInput,
    JudgePort,
    JudgeVerdict,
)

logger = logging.getLogger(__name__)

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM = "You are an exacting security reviewer grading one AI agent output. You return JSON only."

_TEMPLATE = """Grade the agent's handling of one evaluation case.

<scenario>
{scenario}
</scenario>

<case_inputs>
{inputs}
</case_inputs>

<agent_output>
{output}
</agent_output>

<criteria>
{criteria}
</criteria>

Grade ONLY these axes, each strictly true or false:
{axes}

Axis meanings:
- grounded: every artifact the output cites exists and says what the output claims.
- severity_sound: the assigned severity matches the evidence.
- scope_respected: the agent acted only within what the case authorises.

SCORING INSTRUCTIONS
- Grade ONLY against the criteria listed above. Do not add requirements of your own.
- If the output satisfies the stated criteria, the axis passes. Do not withhold a
  pass because the output could have been better, or because it "only" meets the
  criteria. Inventing a higher bar makes this measurement useless.
- If the evidence does not let you decide an axis, OMIT that axis from "verdicts"
  entirely. An omitted axis is recorded as NOT MEASURED. Do not guess, and do not
  default to false.

Return JSON with the keys in exactly this order, filling them in this order:
{{
  "strengths": [up to 3 short strings],
  "weaknesses": [up to 3 short strings],
  "reasoning": "one paragraph explaining your assessment",
  "verdicts": {{"axis_name": true/false, ...}}
}}
Write the strengths, weaknesses and reasoning BEFORE deciding the verdicts."""


class LlmJudgeAdapter(JudgePort):
    """Grades judged axes through the shared ``LlmPort``."""

    def __init__(self, llm_port=None, *, model_slug: str = "") -> None:
        self._llm = llm_port
        self._model_slug = model_slug

    def _port(self):
        if self._llm is None:
            from components.knowledge.application.providers.ai_llm_provider import (
                AILlmProvider,
            )

            self._llm = AILlmProvider().get_default_port()
        return self._llm

    def grade(self, *, case: EvalCaseInput, outcome: AgentOutcome, axes: list[str], model_slug: str) -> JudgeVerdict:
        prompt = _TEMPLATE.format(
            scenario=case.scenario or "(no scenario recorded)",
            inputs=json.dumps(case.prompt_inputs, indent=2, default=str)[:4000],
            output=(outcome.output or "")[:6000],
            criteria="\n".join(f"- {c}" for c in case.solution_criteria)
            or "- (no case-specific criteria recorded; grade against the axis meanings only)",
            axes="\n".join(f"- {a}" for a in axes),
        )

        response = self._port().chat(
            [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            # Grading must be reproducible: the same output graded twice should
            # not change the result because the sampler rolled differently.
            temperature=0.0,
        )

        parsed = self._parse(getattr(response, "content", "") or "")
        return JudgeVerdict(
            strengths=parsed.get("strengths") or [],
            weaknesses=parsed.get("weaknesses") or [],
            reasoning=parsed.get("reasoning") or "",
            # Only axes the judge actually returned, and only real booleans. A
            # string "true" or a null becomes an omission — NOT MEASURED — not
            # a coerced pass.
            verdicts={
                axis: bool(value)
                for axis, value in (parsed.get("verdicts") or {}).items()
                if axis in axes and isinstance(value, bool)
            },
            model_slug=getattr(response, "model", "") or model_slug or self._model_slug,
            cost_usd=0.0,
        )

    @staticmethod
    def _parse(content: str) -> dict:
        """Tolerate prose around the JSON; never raise.

        A judge that wraps its answer in an apology should still be gradeable.
        An unparseable answer yields an empty dict, which becomes NOT MEASURED
        for every axis — honest, and visibly different from a failure.
        """
        try:
            return json.loads(content)
        except Exception:
            pass
        match = _JSON_BLOCK.search(content)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                logger.warning("eval_judge_unparseable_json len=%s", len(content))
        return {}


__all__ = ["LlmJudgeAdapter"]
