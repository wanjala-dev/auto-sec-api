"""deepagents.RubricMiddleware wiring — the grader-with-tools verification loop.

This is the convergence point of the LangChain 1.x migration (plan §7): the
hand-rolled ``critic.WorkerCritic`` / ``reflective_worker`` loop is replaced by
``deepagents.RubricMiddleware`` attached to the worker's ``create_agent`` graph.
The middleware grades each worker answer against the per-agent rubric and
re-runs the agent (bounded) with the grader's feedback when it fails.

The three non-negotiables (per the migration plan):

1. **Cheap grader tier.** The grader model is ``gpt-4o-mini`` (resolved through
   the agent's LLM provider port, so provider swaps still apply).
2. **Bounded.** ``max_iterations`` ≤ 2 — re-run returns diminish sharply after
   the first reflection (Huang et al., ICLR 2024).
3. **Evidence-grounded grading.** The grader carries a TOOL wrapping our
   deterministic grounded verifier (``tools/finding_verifier.verify_suggestion``)
   so the verdict is checked against the finding's actual evidence (error lines,
   measured frequencies) — not the LLM's own read of the answer text. This
   unifies the previously-separate LLM critic and deterministic verifier.

Gating (the hand-rolled critic stays the default until the swap is verified):

- Global: Django setting ``DEEP_RUBRIC_MIDDLEWARE_ENABLED`` (default ``False``).
- Per-agent: ``Agent.config["rubric_middleware"]`` (truthy / dict of options).
- Per-type: only agents in ``critic.CRITIC_ENABLED_AGENTS`` (triage /
  optimization) get the middleware — same opt-in set the critic used. Other
  agents get ``None`` (no middleware, no cost).

When the middleware is active for a run, ``runner.execute_plan_once`` skips the
``reflective_worker`` wrap so the answer is verified by exactly one loop.
"""

from __future__ import annotations

import json
import logging

from .critic import CRITIC_ENABLED_AGENTS, RUBRICS

logger = logging.getLogger(__name__)

# Cheap grader tier (plan §7: "grader model = cheap tier").
GRADER_MODEL = "gpt-4o-mini"
GRADER_TEMPERATURE = 0.1
# Hard cap regardless of config — the loop must stay bounded.
MAX_ITERATIONS_CAP = 2

_GRADER_SYSTEM_PROMPT = (
    "You are grading a security analyst agent's answer to one task against the "
    "rubric below. Before deciding, call the `verify_suggestion_grounded` tool "
    "with the answer's suggestion text — it deterministically checks the answer "
    "against the finding's ACTUAL evidence (error lines, symbols, measured "
    "frequencies). If the tool reports the answer is not grounded, the answer "
    "fails regardless of how plausible it reads. Only fail an answer on rubric "
    "grounds when it clearly misses a criterion; marginal answers pass "
    "(re-running a marginal answer risks over-correction). Give feedback that "
    "names exactly what is missing."
)


def rubric_middleware_enabled(agent_config: dict | None = None) -> bool:
    """Is the RubricMiddleware verification loop switched on?

    True when either the global Django setting or the agent/run config opts in.
    """
    if isinstance(agent_config, dict) and agent_config.get("rubric_middleware"):
        return True
    try:
        from django.conf import settings

        return bool(getattr(settings, "DEEP_RUBRIC_MIDDLEWARE_ENABLED", False))
    except Exception:
        return False


def _resolve_agent_type(agent) -> str:
    """The registry slug for this BaseAgent instance (e.g. ``triage_agent``)."""
    configured = (agent.config or {}).get("agent_type") if getattr(agent, "config", None) else None
    if configured:
        return str(configured).strip()
    return str(getattr(type(agent), "_canonical_agent_name", "") or "").strip()


def build_grader_verifier_tool(agent):
    """The grader's grounding tool — wraps ``finding_verifier.verify_suggestion``.

    The finding's evidence is loaded from the kanban Task row the worker is
    processing (``task_id``), exactly like the worker's own ``process_finding``
    tools do — so the grader checks against the same ground truth, scoped to
    the agent's workspace. With no resolvable finding it reports "no evidence"
    and the grader falls back to rubric-only judgment (conservative, mirrors
    ``finding_verifier``'s pass-when-undecidable stance).
    """
    from langchain_core.tools import StructuredTool

    def verify_suggestion_grounded(suggestion_text: str, task_id: str = "") -> str:
        from components.agents.infrastructure.adapters.langchain.tools.finding_verifier import (
            verify_suggestion,
        )

        source_type = ""
        payload: dict = {}
        resolved = False
        if task_id:
            try:
                from infrastructure.persistence.project.models import Task

                task = Task.objects.filter(id=task_id, workspace_id=agent.workspace_id).first()
                if task is not None:
                    meta = task.metadata or {}
                    payload = meta.get("payload") or {}
                    source_type = str(task.source_type or meta.get("source_type") or "")
                    resolved = True
            except Exception:
                logger.warning("rubric grader could not load finding task_id=%s", task_id, exc_info=True)

        if not resolved:
            return json.dumps(
                {
                    "grounded": None,
                    "reason": ("No finding evidence available (missing/unknown task_id) — grade on the rubric alone."),
                }
            )

        result = verify_suggestion(
            source_type=source_type,
            payload=payload,
            suggestion_text=suggestion_text or "",
        )
        return json.dumps({"grounded": result.grounded, "reason": result.reason})

    return StructuredTool.from_function(
        func=verify_suggestion_grounded,
        name="verify_suggestion_grounded",
        description=(
            "Deterministically verify that a suggested fix/recommendation is "
            "grounded in the finding's stored evidence. Pass the suggestion "
            "text and, when known, the finding's task_id (a UUID mentioned in "
            "the task). Returns JSON {grounded, reason}."
        ),
    )


def resolve_rubric_text(agent) -> str | None:
    """The rubric string for this agent's type, or ``None`` when not gradable.

    deepagents 0.6.12 delivers the rubric via the **invocation state**
    (``state["rubric"]``) — with no rubric on the state the middleware is a
    no-op. ``_GraphExecutorHandle`` calls this through its
    ``rubric_provider`` on every invoke so critic-enabled agents are graded
    and every other agent runs middleware-free-in-effect.
    """
    agent_type = _resolve_agent_type(agent)
    if agent_type not in CRITIC_ENABLED_AGENTS:
        return None
    return RUBRICS.get(agent_type) or None


class RubricEvaluationCollector:
    """Accumulates the grader's per-iteration evaluations for one agent.

    deepagents 0.6.12 keeps its grading bookkeeping (``_rubric_evaluations``,
    ``_rubric_status``) in ``PrivateStateAttr`` state keys that are STRIPPED
    from the graph's output schema — the only in-process observation channels
    are the ``on_evaluation`` callback, the ``rubric_evaluation_*`` stream
    events, or ``get_state()`` on a checkpointed thread. Our worker graphs
    are deliberately not checkpointed (conversation memory is SQL-backed)
    and we don't consume the stream, so this collector — wired in as the
    middleware's ``on_evaluation`` — IS the telemetry tap.

    Each evaluation is a ``RubricEvaluation`` **TypedDict** (a plain dict at
    runtime) with keys ``grading_run_id`` / ``iteration`` / ``result`` /
    ``explanation`` / ``criteria`` — NOT an object with ``verdict`` /
    ``feedback`` attributes (the bug this class replaced: ``getattr`` on a
    dict returned ``None`` for every field).

    Per-evaluation ``result`` ∈ {satisfied, needs_revision, failed,
    grader_error}; ``max_iterations_reached`` never appears on an evaluation
    (the middleware records it only on the private ``_rubric_status``) — see
    ``summarize_rubric_evaluations`` for the mirrored derivation.

    Fail-safe discipline: ``record`` never raises (a telemetry bug must not
    break grading — deepagents also guards the callback, but we degrade to a
    warning ourselves rather than rely on it).
    """

    def __init__(self, *, grader_model: str, max_iterations: int) -> None:
        self.grader_model = grader_model
        self.max_iterations = max_iterations
        self._evaluations: list[dict] = []

    def record(self, evaluation) -> None:
        """``on_evaluation`` callback — capture + log one grader evaluation."""
        try:
            data = self._normalize(evaluation)
            self._evaluations.append(data)
            logger.info(
                "rubric_evaluation verdict=%s iteration=%s run_id=%s feedback=%s",
                data["result"],
                data["iteration"],
                data["grading_run_id"],
                (data["explanation"] or "")[:300],
            )
        except Exception:
            logger.warning("rubric evaluation capture failed", exc_info=True)

    @staticmethod
    def _normalize(evaluation) -> dict:
        """Coerce a ``RubricEvaluation`` (TypedDict → plain dict) to our shape.

        Dict access is the real 0.6.12 location; attribute access is kept
        only as forward-compat should a future release turn the evaluation
        into a model object.
        """
        if isinstance(evaluation, dict):
            get = evaluation.get
        else:

            def get(key, default=None):
                return getattr(evaluation, key, default)

        criteria = []
        for criterion in get("criteria") or []:
            if isinstance(criterion, dict):
                criteria.append(
                    {
                        "name": str(criterion.get("name") or ""),
                        "passed": bool(criterion.get("passed")),
                        "gap": str(criterion.get("gap") or ""),
                    }
                )
        return {
            "grading_run_id": str(get("grading_run_id") or ""),
            "iteration": get("iteration"),
            "result": str(get("result") or ""),
            "explanation": str(get("explanation") or ""),
            "criteria": criteria,
        }

    def drain(self) -> list[dict]:
        """Return and clear everything recorded since the last drain."""
        evaluations, self._evaluations = self._evaluations, []
        return evaluations


def summarize_rubric_evaluations(evaluations, *, max_iterations: int, grader_model: str) -> dict | None:
    """Fold one invoke's evaluations into the ``rubric_verdicts`` stamp.

    Shape mirrors the critic's ``run_metadata["critic_scores"][task_id]``
    stamp (same consumers: the run trace + the future L4 hill-climbing
    loop): ``{"verdict", "iterations", "feedback", "grader", "source"}``
    plus the observed per-iteration ``results`` and the ``grading_run_id``.

    ``verdict`` is the last evaluation's ``result``, EXCEPT that a terminal
    ``needs_revision`` with the iteration budget exhausted is reported as
    ``max_iterations_reached`` — the exact mapping the middleware applies to
    its private ``_rubric_status`` (``RubricMiddleware._compose_update``),
    which we cannot read from the graph output.
    """
    if not evaluations:
        return None
    last = evaluations[-1]
    run_id = last.get("grading_run_id") or ""
    run_evaluations = [e for e in evaluations if (e.get("grading_run_id") or "") == run_id]
    iterations = len(run_evaluations)

    verdict = str(last.get("result") or "")
    if verdict == "needs_revision" and iterations >= max_iterations:
        verdict = "max_iterations_reached"

    feedback = str(last.get("explanation") or "")
    gaps = [
        f"{c.get('name') or '(criterion)'}: {c.get('gap')}"
        for c in (last.get("criteria") or [])
        if not c.get("passed") and c.get("gap")
    ]
    if gaps:
        feedback = f"{feedback} | gaps: {'; '.join(gaps)}".strip(" |")

    return {
        "verdict": verdict,
        "iterations": iterations,
        "feedback": feedback[:500],
        "grader": grader_model,
        "source": "rubric_middleware",
        "grading_run_id": run_id,
        "results": [str(e.get("result") or "") for e in run_evaluations],
    }


def drain_rubric_evaluations(agent) -> dict | None:
    """Pop the agent collector's evaluations for the invoke that just ran.

    Returns ``{"evaluations": [...], "max_iterations": int, "grader": str}``
    or ``None`` when there is no collector / nothing was graded. Called by
    ``BaseAgent.execute`` so the payload rides the response to the deep-run
    worker (which owns the task_id needed for stamping). Never raises.
    """
    try:
        collector = getattr(agent, "_rubric_evaluation_collector", None)
        if collector is None:
            return None
        evaluations = collector.drain()
        if not evaluations:
            return None
        return {
            "evaluations": evaluations,
            "max_iterations": collector.max_iterations,
            "grader": collector.grader_model,
        }
    except Exception:
        logger.warning("rubric evaluation drain failed", exc_info=True)
        return None


def rubric_run_metadata_update(*, state, response, task_id) -> dict | None:
    """The worker-delta ``run_metadata`` carrying this task's rubric verdict.

    ``None`` when the response carries no rubric evaluations (middleware off,
    non-gradable agent type, or nothing graded). Seeds from the state's
    current ``run_metadata`` because ``PlanState.run_metadata`` has no merge
    reducer (last write wins) — without the seed each task's stamp would
    clobber the previous task's. Never raises: extraction failure degrades
    to a warning, the run continues unstamped.
    """
    try:
        drained = (response or {}).get("rubric_evaluations") if isinstance(response, dict) else None
        if not drained:
            return None
        stamp = summarize_rubric_evaluations(
            drained.get("evaluations") or [],
            max_iterations=int(drained.get("max_iterations") or MAX_ITERATIONS_CAP),
            grader_model=str(drained.get("grader") or GRADER_MODEL),
        )
        if stamp is None:
            return None
        run_metadata = dict((state or {}).get("run_metadata") or {})
        verdicts = dict(run_metadata.get("rubric_verdicts") or {})
        verdicts[str(task_id)] = stamp
        run_metadata["rubric_verdicts"] = verdicts
        return run_metadata
    except Exception:
        logger.warning("rubric verdict stamping failed task_id=%s", task_id, exc_info=True)
        return None


def build_rubric_middleware(*, agent, config: dict | None = None):
    """Build a ``deepagents.RubricMiddleware`` for this agent, or ``None``.

    ``None`` (no middleware) when the agent's type has no rubric — grading an
    agent with no measurable criteria is pure cost, same opt-in rule the
    hand-rolled critic used.

    Actual deepagents 0.6.12 signature (verified against the installed
    package): ``RubricMiddleware(*, model, system_prompt=None, tools=None,
    max_iterations=3, on_evaluation=None)``. ``model`` is REQUIRED; the
    rubric itself is NOT a constructor arg — it rides the invocation state
    (see ``resolve_rubric_text``).
    """
    if resolve_rubric_text(agent) is None:
        return None

    from deepagents.middleware.rubric import RubricMiddleware

    cfg = config if isinstance(config, dict) else {}
    try:
        max_iterations = int(cfg.get("max_iterations", MAX_ITERATIONS_CAP))
    except (TypeError, ValueError):
        max_iterations = MAX_ITERATIONS_CAP
    max_iterations = max(1, min(max_iterations, MAX_ITERATIONS_CAP))

    grader_model_name = str(cfg.get("grader_model") or GRADER_MODEL)
    try:
        grader_model = agent._resolve_llm_provider().get_llm(
            provider_slug=(agent.config or {}).get("provider", "openai"),
            model_name=grader_model_name,
            temperature=GRADER_TEMPERATURE,
        )
    except Exception:
        # `model` is required — fall back to the provider:model string form
        # (resolved lazily by the middleware) rather than disabling
        # verification because the port failed to hand us an instance.
        logger.warning("rubric grader model port resolution failed; using model string", exc_info=True)
        grader_model = f"openai:{grader_model_name}"

    # The collector is the ONLY in-process tap for grader verdicts (see its
    # docstring); attach it to the agent so BaseAgent.execute can drain it
    # per invoke and ship the evaluations out on the response.
    collector = RubricEvaluationCollector(
        grader_model=grader_model_name,
        max_iterations=max_iterations,
    )
    agent._rubric_evaluation_collector = collector

    middleware = RubricMiddleware(
        model=grader_model,
        system_prompt=_GRADER_SYSTEM_PROMPT,
        tools=[build_grader_verifier_tool(agent)],
        max_iterations=max_iterations,
        on_evaluation=collector.record,
    )
    logger.info(
        "rubric_middleware attached agent_type=%s max_iterations=%s grader=%s",
        _resolve_agent_type(agent),
        max_iterations,
        grader_model_name,
    )
    return middleware
