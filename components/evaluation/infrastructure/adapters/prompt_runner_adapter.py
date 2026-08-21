"""Run one case against a bare SYSTEM PROMPT (ADR 0033 D15, prompt mode).

The agent runner beside this executes the real agent: tools, retrieval, its
registry-versioned prompt. This one executes a prompt the operator typed, on its
own, and nothing else. That difference is the entire point of the mode — it is
what makes "is this prompt better than the one I am running?" a question with a
clean answer, because only the prompt varies.

It is also why the two scores are never comparable, and why `EvalSuite.mode`
exists rather than a flag someone has to remember to check.

Two properties worth stating, both consequences of there being no tools:

**D5 is satisfied structurally, not by a guard.** The evaluation-mode tool gate
exists because a real agent could write. Here there is no tool call to gate: the
model is handed a system prompt and a user message and returns text. There is
nothing for it to mutate.

**A case costs one call, not a loop.** A 200-case prompt suite is minutes and
cents rather than hours — which is what makes iterating on a prompt inside the
product realistic at all.

The uploaded prompt is UNTRUSTED text that becomes a system prompt. That is
worth being clear-eyed about rather than reassuring: the operator is deliberately
running their own instructions, in their own workspace, against their own cases,
with no tools attached and the output going nowhere but their own eval result.
The blast radius is their own reading of their own experiment.
"""

from __future__ import annotations

import logging

from components.evaluation.application.ports.eval_ports import (
    AgentOutcome,
    AgentRunnerPort,
    EvalCaseInput,
)

logger = logging.getLogger(__name__)

def render_user_message(case: EvalCaseInput) -> str:
    """The case as the prompt under test will receive it.

    Deliberately the SAME rendering the agent runner uses, so a case means the
    same thing in both modes. If the two drifted, a suite moved from prompt mode
    to agent mode would silently be asking different questions.
    """
    lines = [f"Evaluation case: {case.scenario or case.case_id}", ""]
    for key, value in (case.prompt_inputs or {}).items():
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


class PromptRunnerAdapter(AgentRunnerPort):
    """Executes a system prompt against one case. No tools, no retrieval."""

    def __init__(self, *, system_prompt: str, llm_port=None) -> None:
        self._system_prompt = system_prompt or ""
        self._llm = llm_port

    def run_case(self, *, agent_type: str, workspace_id: str, case: EvalCaseInput, model_slug: str) -> AgentOutcome:
        if not self._system_prompt.strip():
            # An empty prompt is not a zero-scoring prompt, it is a
            # misconfiguration. Running it would produce verdicts about nothing
            # and report them as the prompt's quality.
            return AgentOutcome(output="", error="this suite has no system prompt to test")

        try:
            response = self._port().chat(
                [
                    {"role": "system", "content": self._system_prompt},
                    {"role": "user", "content": render_user_message(case)},
                ],
                # Deterministic for the same reason the judge is: comparing two
                # prompts requires that the ONLY thing varying is the prompt. A
                # non-zero temperature would let the sampler move a score.
                temperature=0.0,
            )
        except Exception as exc:
            logger.exception("eval_prompt_run_failed case=%s model=%s", case.case_id, model_slug)
            return AgentOutcome(output="", error=str(exc))

        text = getattr(response, "content", "") or ""
        return AgentOutcome(
            output=str(text),
            cost_usd=float(getattr(response, "cost_usd", 0.0) or 0.0),
            error="" if str(text).strip() else "the prompt produced no output for this case",
        )

    def _port(self):
        """Resolved through the knowledge provider, exactly as the judge adapter
        does it — one way to reach the LLM in this context, not two."""
        if self._llm is None:
            from components.knowledge.application.providers.ai_llm_provider import AILlmProvider

            self._llm = AILlmProvider().get_default_port()
        return self._llm


__all__ = ["PromptRunnerAdapter", "render_user_message"]
