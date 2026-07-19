"""Verification loop (L2) — a bounded critic that grades worker output and,
on failure, sends the task back to the same worker with feedback.

This is the *evaluator-optimizer* / *Reflexion-at-the-task-level* pattern
(see docs/plans/LOOP_ENGINEERING_SELF_IMPROVEMENT_2026-07-19.md). The worker
generates; the critic evaluates against a rubric; a failing result is re-run
ONCE (bounded — returns diminish sharply after the first reflection) with the
critique appended to the task so the agent can see what to fix.

Design discipline (from Anthropic "Building Effective Agents" + the LangChain
loop-engineering model):
- **Cheap first gate.** The deterministic honesty guard (``_is_agent_failure_summary``)
  catches tool-failure / fabrication summaries with NO LLM spend; only when it
  passes do we spend an LLM critic on the rubric.
- **Fail-safe.** Any critic error degrades to "passed" — the critic is an
  enhancement, never a gate that can block a run (mirrors the advisors' degrade-
  to-None discipline).
- **Opt-in per agent.** Only agents with clear rubrics are graded
  (``CRITIC_ENABLED_AGENTS``); a critic with no measurable criteria is pure cost.
- **Bounded.** ``max_reflections`` caps the loop (default 1); the third pass
  isn't worth the latency.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from .orchestrator import _is_agent_failure_summary

logger = logging.getLogger(__name__)

# Only agents whose output has a clear, gradable rubric. A reflection loop on an
# agent with no measurable criteria is latency + cost for no gain.
CRITIC_ENABLED_AGENTS = {"triage_agent", "optimization_agent"}

# Below this the result is treated as failing even if the grader says "passed".
_PASS_SCORE = 6
# Below this a fail is "confident" enough to justify a re-run. A marginal fail
# (score in [_CONFIDENT_FAIL_FLOOR, _PASS_SCORE)) is accepted as-is rather than
# risked to an over-correction re-run — pure LLM self-critique reliably improves
# only confident failures; on marginal ones it can make a correct answer worse
# (Huang et al., ICLR 2024, "LLMs Cannot Self-Correct Reasoning Yet").
_CONFIDENT_FAIL_FLOOR = 4
_TEMPERATURE = 0.1
# Optional cheap grader model (RubricMiddleware defaults its grader to a small
# model). None = the provider default (what the advisors already use). Point at a
# confirmed-configured cheap tier to cut grading cost; a bad name safely falls
# back to the default rather than silently disabling the critic.
_GRADER_MODEL = None

# Per-agent rubrics — short, VERIFIABLE checklists (RubricMiddleware-style). The
# grader appends the matching rubric so the holistic grade targets concrete
# criteria, not vibes. Hard groundedness is enforced deterministically in
# finding_verifier.py; these guide the LLM's overall judgment.
RUBRICS = {
    "triage_agent": (
        "- Names the specific module/symbol/config from the error, not generic advice.\n"
        "- The likely cause is grounded in the actual error line.\n"
        "- The fix is a concrete next step an on-call engineer can act on."
    ),
    "optimization_agent": (
        "- Names the actual over-scheduled task/service from the pattern.\n"
        "- Proposes a concrete change (longer interval, sampling, or dropping the log),"
        " grounded in the measured frequency.\n"
        "- States the resource win."
    ),
}

_SYSTEM = (
    "You are grading a security analyst agent's answer to one task. You are given "
    "the task and the agent's answer. Judge whether the answer: (1) is grounded — "
    "it engages with the specific finding/evidence, not generic boilerplate; (2) "
    "actually addresses the task; (3) is concrete and actionable, not vague "
    "hedging; (4) is free of fabrication (no invented data). Respond with STRICT "
    "JSON and nothing else, shaped exactly:\n"
    '{"passed": true|false, "score": <0-10 integer>, "feedback": "<one or two '
    'sentences telling the agent exactly what to fix; empty string if passed>"}\n'
    "Be specific in feedback — name what was missing. No preamble, JSON only."
)


@dataclass(frozen=True)
class CriticVerdict:
    passed: bool
    score: int
    feedback: str


class WorkerCritic:
    """Grades one worker answer against the SOC-analyst rubric."""

    def __init__(self, llm_port=None) -> None:
        self._llm = llm_port

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        from components.knowledge.application.providers.ai_llm_provider import AILlmProvider

        provider = AILlmProvider()
        # Try, in order: cheap grader model (if configured) → default with
        # max_tokens → default. Each falls back so a bad/unconfigured model name
        # never silently disables the critic (it just uses the working default).
        attempts = []
        if _GRADER_MODEL:
            attempts.append({"model_name": _GRADER_MODEL, "temperature": _TEMPERATURE, "max_tokens": 300})
        attempts += [{"temperature": _TEMPERATURE, "max_tokens": 300}, {"temperature": _TEMPERATURE}]
        for kwargs in attempts:
            try:
                self._llm = provider.get_default_port(**kwargs)
                return self._llm
            except (TypeError, KeyError, ValueError):
                continue
        # Last resort — the plain default.
        self._llm = provider.get_default_port()
        return self._llm

    def grade(
        self, *, task_title: str, task_description: str, answer: str, agent_type: str | None = None
    ) -> CriticVerdict:
        """Return a verdict. Never raises — a critic failure means "passed"."""
        # Cheap deterministic gate first — a tool-failure / empty summary is a
        # definite fail without spending an LLM.
        if _is_agent_failure_summary(answer or ""):
            return CriticVerdict(
                passed=False,
                score=0,
                feedback=(
                    "Your last attempt returned a tool-failure or empty result. Actually call your "
                    "tools and ground the answer in the finding's evidence."
                ),
            )

        # Append the per-agent rubric (RubricMiddleware-style) so the grade
        # targets concrete, verifiable criteria rather than a vibe.
        system = _SYSTEM
        rubric = RUBRICS.get((agent_type or "").strip())
        if rubric:
            system = f"{_SYSTEM}\n\nGrade specifically against this rubric — each line is a criterion:\n{rubric}"

        prompt = (
            f"Task title: {task_title}\n"
            f"Task detail: {(task_description or '')[:1200]}\n\n"
            f"Agent answer:\n{(answer or '')[:2000]}\n\n"
            "Return the JSON now."
        )
        try:
            llm = self._get_llm()
            response = llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            logger.exception("worker_critic llm call failed; passing (fail-safe)")
            return CriticVerdict(passed=True, score=_PASS_SCORE, feedback="")

        return self._parse(getattr(response, "content", "") or "")

    @staticmethod
    def _parse(content: str) -> CriticVerdict:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            logger.warning("worker_critic unparseable output; passing (fail-safe)")
            return CriticVerdict(passed=True, score=_PASS_SCORE, feedback="")
        try:
            score = int(data.get("score", _PASS_SCORE))
        except (ValueError, TypeError):
            score = _PASS_SCORE
        passed = bool(data.get("passed", True)) and score >= _PASS_SCORE
        feedback = str(data.get("feedback") or "").strip()
        return CriticVerdict(passed=passed, score=score, feedback=feedback)


def _summary_of(result) -> str:
    """Extract the worker's answer text from its state delta."""
    if not isinstance(result, dict):
        return ""
    completed = result.get("completed_tasks") or []
    if completed:
        first = completed[0]
        return str(getattr(first, "summary", None) or (first.get("summary") if isinstance(first, dict) else "") or "")
    return ""


def reflective_worker(base_worker, critic, *, max_reflections, agent_type_of, enabled_agents=CRITIC_ENABLED_AGENTS):
    """Wrap a worker_fn with a bounded verification loop.

    The graph is untouched — reflection is a property of the worker (the L2 loop
    wraps the L1 agent loop). Only tasks whose effective agent_type is in
    ``enabled_agents`` are graded; everything else passes straight through with
    zero added cost.

    Args:
        base_worker: the underlying ``worker_fn(state) -> state_delta``.
        critic: a ``WorkerCritic`` (or anything with a compatible ``grade``).
        max_reflections: max re-run passes (0 disables; 1 is the sweet spot).
        agent_type_of: ``(task) -> str`` resolving the EFFECTIVE agent type
            (mirrors the runner's force-worker override) so the enabled-check
            matches what actually runs.
        enabled_agents: the set of agent types to grade.
    """

    def wrapped(state):
        task = state.get("task")
        result = base_worker(state)
        if task is None or max_reflections <= 0:
            return result
        atype = (agent_type_of(task) or "").strip()
        if atype not in enabled_agents:
            return result

        scores: list[int] = []
        reflections = 0
        answer = _summary_of(result)
        # Keep the BEST-scored attempt, not the last — a re-run can over-correct
        # and end up WORSE than the original (Huang et al., ICLR 2024). Returning
        # the last attempt would silently ship that regression.
        best_result = result
        best_score = -1
        while True:
            verdict = critic.grade(
                task_title=getattr(task, "title", "") or "",
                task_description=getattr(task, "description", "") or "",
                answer=answer,
                agent_type=atype,
            )
            scores.append(verdict.score)
            if verdict.score > best_score:
                best_score, best_result = verdict.score, result
            # Stop when: passed, out of budget, OR only a MARGINAL fail (a re-run
            # would risk an over-correction for little expected gain — only a
            # confident fail justifies spending another pass).
            if verdict.passed or reflections >= max_reflections or verdict.score >= _CONFIDENT_FAIL_FLOOR:
                break
            # Reflexion: append the critique so the re-run's agent sees exactly
            # what to fix (the worker builds its input from task.title/description).
            task.description = (
                getattr(task, "description", "") or ""
            ) + f"\n\nPrior attempt feedback (address this specifically): {verdict.feedback}"
            logger.info(
                "worker_critic reflect task_id=%s agent=%s score=%s",
                getattr(task, "id", None),
                atype,
                verdict.score,
            )
            result = base_worker(state)
            answer = _summary_of(result)
            reflections += 1

        # Stamp observability on the RETURNED (best) result so the run trace +
        # L4 hill-climbing can read critic scores.
        if isinstance(best_result, dict):
            run_metadata = dict(best_result.get("run_metadata") or {})
            critic_scores = dict(run_metadata.get("critic_scores") or {})
            critic_scores[str(getattr(task, "id", "") or "")] = {
                "agent": atype,
                "scores": scores,
                "best_score": best_score,
                "reflections": reflections,
            }
            run_metadata["critic_scores"] = critic_scores
            best_result["run_metadata"] = run_metadata
        return best_result

    return wrapped
