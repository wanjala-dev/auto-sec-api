"""``PromptEvaluator`` — the harness that drives the 5-step workflow.

Mirrors the Logseq curriculum's TypeScript ``PromptEvaluator`` class
but lives where the prompts under test live: the Django backend.
Callers supply:

- ``run_prompt_function(case) -> PlanSpec | None`` — runs the prompt
  under test for one case.
- ``code_grader(plan, case) -> AggregateCodeGrade-like`` — deterministic
  scoring. Lives in ``tests/prompt_eval/graders/code/``.
- ``model_grader(case, plan_payload) -> ModelGradeResult-like`` —
  LLM-as-judge. Lives in ``tests/prompt_eval/graders/model/``.

The harness is grader-agnostic — it just calls the callables and
treats their results as opaque objects with the duck-typed surface
the HTML report renders (``overall_score``, ``score``, ``reasons_flat()``,
``strengths``, ``weaknesses``, ``reasoning``, ``error``, ``is_error``).

Concurrency is bounded by ``max_concurrent_tasks`` (default 3) so a
naive eval doesn't trip rate limits. Code graders are deterministic
and run inline; only the model grader actually awaits an LLM call.

Plan reference: ``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``
Wave 2.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from components.agents.domain.value_objects.plan_schemas import PlanSpec

logger = logging.getLogger(__name__)


RunPromptFunction = Callable[[dict[str, Any]], PlanSpec | None]
CodeGraderFn = Callable[[PlanSpec | None, dict[str, Any]], Any]
ModelGraderFn = Callable[[dict[str, Any], dict[str, Any]], Any]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class TestCaseResult:
    """One test case's full eval result.

    ``code_grade`` and ``model_grade`` are duck-typed — see the module
    docstring. They expose ``overall_score`` / ``score`` for the
    headline number, ``reasons_flat()`` / ``strengths`` / ``weaknesses``
    / ``reasoning`` for the HTML report, and ``error`` / ``is_error``
    for grader-side failures.
    """

    case_id: str
    category: str
    goal: str
    expected_agent_type: str | None
    plan_payload: dict[str, Any] | None
    code_grade: Any
    model_grade: Any
    overall_score: float

    def to_serialisable(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "category": self.category,
            "goal": self.goal,
            "expected_agent_type": self.expected_agent_type,
            "plan_payload": self.plan_payload,
            "code_grade": _serialise_code_grade(self.code_grade),
            "model_grade": _serialise_model_grade(self.model_grade),
            "overall_score": self.overall_score,
        }


@dataclass
class EvaluationReport:
    """Aggregate output of one ``run_evaluation`` invocation."""

    dataset_name: str
    started_at: str
    finished_at: str
    grader_model: str
    case_count: int
    average_score: float
    pass_rate_at_seven: float
    score_by_category: dict[str, float]
    results: list[TestCaseResult] = field(default_factory=list)

    def to_serialisable(self) -> dict[str, Any]:
        return {
            "dataset_name": self.dataset_name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "grader_model": self.grader_model,
            "case_count": self.case_count,
            "average_score": self.average_score,
            "pass_rate_at_seven": self.pass_rate_at_seven,
            "score_by_category": self.score_by_category,
            "results": [r.to_serialisable() for r in self.results],
        }


# ---------------------------------------------------------------------------
# The evaluator
# ---------------------------------------------------------------------------


class PromptEvaluator:
    """Drives one ``run_prompt_function`` through a dataset.

    Public surface:

    - ``__init__(*, code_grader, model_grader, max_concurrent_tasks=3, grader_label="gpt-4o-mini")``
    - ``run_evaluation(*, run_prompt_function, dataset_path, dataset_name=None) -> EvaluationReport``
    - ``write_html_report(report, output_path)``
    - ``write_json_report(report, output_path)``

    Graders are injected so the harness can score any prompt set. See
    ``components/agents/tests/prompt_eval/graders/`` for the planner's
    code + model graders; other prompts ship their own.

    The harness does **not** generate datasets. Hand-author them and
    commit to ``components/agents/tests/prompt_eval/datasets/`` per the
    plan's "Datasets are seed data, not frontend constants" rule.
    """

    def __init__(
        self,
        *,
        code_grader: CodeGraderFn,
        model_grader: ModelGraderFn,
        max_concurrent_tasks: int = 3,
        grader_label: str = "gpt-4o-mini",
    ) -> None:
        if max_concurrent_tasks < 1:
            raise ValueError("max_concurrent_tasks must be >= 1")
        self._code_grader = code_grader
        self._model_grader = model_grader
        self._max_concurrent_tasks = max_concurrent_tasks
        self._grader_label = grader_label

    # ── Dataset I/O ────────────────────────────────────────────────────

    @staticmethod
    def load_dataset(dataset_path: str | Path) -> dict[str, Any]:
        """Load a JSON dataset and validate the minimal shape."""
        path = Path(dataset_path)
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "cases" not in data:
            raise ValueError(
                f"Dataset {path} must be a JSON object with a top-level "
                "'cases' array"
            )
        return data

    # ── Main entry ─────────────────────────────────────────────────────

    def run_evaluation(
        self,
        *,
        run_prompt_function: RunPromptFunction,
        dataset_path: str | Path,
        dataset_name: str | None = None,
    ) -> EvaluationReport:
        """Synchronous wrapper around ``run_evaluation_async``.

        The graders' I/O (model grader's LLM call) benefits from
        concurrency, so the inner loop is async; this wrapper just
        runs it on the calling thread's event loop. Django
        management commands are synchronous, so this is the form
        most callers want.
        """
        return asyncio.run(
            self.run_evaluation_async(
                run_prompt_function=run_prompt_function,
                dataset_path=dataset_path,
                dataset_name=dataset_name,
            )
        )

    async def run_evaluation_async(
        self,
        *,
        run_prompt_function: RunPromptFunction,
        dataset_path: str | Path,
        dataset_name: str | None = None,
    ) -> EvaluationReport:
        """Run the dataset, score every case, return the aggregated report."""
        data = self.load_dataset(dataset_path)
        cases: list[dict[str, Any]] = list(data.get("cases") or [])
        meta = data.get("_meta") or {}
        resolved_name = (
            dataset_name or meta.get("name") or Path(dataset_path).stem
        )
        started_at = datetime.now(timezone.utc).isoformat()

        semaphore = asyncio.Semaphore(self._max_concurrent_tasks)

        async def _evaluate(case: dict[str, Any]) -> TestCaseResult:
            async with semaphore:
                return await self._evaluate_one(case, run_prompt_function)

        results = await asyncio.gather(*(_evaluate(case) for case in cases))
        finished_at = datetime.now(timezone.utc).isoformat()

        scores = [r.overall_score for r in results]
        average = statistics.mean(scores) if scores else 0.0
        pass_count = sum(1 for s in scores if s >= 7.0)
        pass_rate = (pass_count / len(scores)) if scores else 0.0

        score_by_category: dict[str, list[float]] = {}
        for result in results:
            score_by_category.setdefault(result.category, []).append(
                result.overall_score
            )

        return EvaluationReport(
            dataset_name=resolved_name,
            started_at=started_at,
            finished_at=finished_at,
            grader_model=self._grader_label,
            case_count=len(results),
            average_score=average,
            pass_rate_at_seven=pass_rate,
            score_by_category={
                cat: statistics.mean(vals) for cat, vals in score_by_category.items()
            },
            results=results,
        )

    # ── Per-case evaluation ────────────────────────────────────────────

    async def _evaluate_one(
        self,
        case: dict[str, Any],
        run_prompt_function: RunPromptFunction,
    ) -> TestCaseResult:
        """Run the prompt function and the graders for one case.

        ``run_prompt_function`` is synchronous (Django ORM-bound, in
        practice). Run it in a thread so it doesn't block the event
        loop; the model grader is also synchronous but is at least
        an HTTP call we can parallelise across cases via the
        outer ``asyncio.Semaphore``.
        """
        case_id = str(case.get("id") or "<unknown>")
        category = str(case.get("category") or "uncategorised")
        goal = str(case.get("goal") or "")
        expected = case.get("expected_agent_type")

        plan: PlanSpec | None
        try:
            plan = await asyncio.to_thread(run_prompt_function, case)
        except Exception as exc:  # noqa: BLE001
            logger.warning("run_prompt_function failed for case=%s: %s", case_id, exc)
            plan = None

        plan_payload = _serialise_plan(plan)

        code_grade = self._code_grader(plan, case)

        model_grade = await asyncio.to_thread(
            self._model_grader,
            case,
            plan_payload or {},
        )

        overall = (code_grade.overall_score + float(model_grade.score)) / 2.0
        return TestCaseResult(
            case_id=case_id,
            category=category,
            goal=goal,
            expected_agent_type=expected if isinstance(expected, str) else None,
            plan_payload=plan_payload,
            code_grade=code_grade,
            model_grade=model_grade,
            overall_score=overall,
        )

    # ── Reports ────────────────────────────────────────────────────────

    @staticmethod
    def write_json_report(report: EvaluationReport, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(report.to_serialisable(), indent=2, default=str),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def write_html_report(report: EvaluationReport, output_path: str | Path) -> Path:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render_html(report), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Helpers — plan serialisation + HTML rendering
# ---------------------------------------------------------------------------


def _serialise_plan(plan: PlanSpec | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    # Grader-agnostic passthrough: prompt families whose artifact is already
    # a plain dict (e.g. the writing eval's generated draft) flow through
    # unchanged. Only PlanSpec-shaped objects get the planner serialisation.
    if isinstance(plan, dict):
        return plan
    tasks = []
    for task in getattr(plan, "tasks", None) or []:
        tasks.append(
            {
                "title": getattr(task, "title", ""),
                "description": getattr(task, "description", "") or "",
                "agent_type": getattr(task, "agent_type", "") or "",
                "priority": getattr(getattr(task, "priority", None), "value", "")
                or str(getattr(task, "priority", "") or ""),
                "status": getattr(getattr(task, "status", None), "value", "")
                or str(getattr(task, "status", "") or ""),
            }
        )
    return {
        "plan_id": getattr(plan, "plan_id", ""),
        "goal": getattr(plan, "goal", ""),
        "task_count": len(tasks),
        "tasks": tasks,
        "metadata": getattr(plan, "metadata", {}) or {},
    }


def _serialise_code_grade(grade: Any) -> dict[str, Any]:
    """Duck-typed serialisation for any AggregateCodeGrade-shaped object."""
    sub_scores = []
    for sub in getattr(grade, "sub_scores", []) or []:
        sub_scores.append(
            {
                "label": getattr(sub, "label", ""),
                "score": getattr(sub, "score", 0),
                "reasons": list(getattr(sub, "reasons", []) or []),
            }
        )
    return {
        "overall_score": getattr(grade, "overall_score", 0.0),
        "sub_scores": sub_scores,
    }


def _serialise_model_grade(grade: Any) -> dict[str, Any]:
    """Duck-typed serialisation for any ModelGradeResult-shaped object.

    Handles both the single-score legacy shape and the multi-axis
    shape. If ``axes`` is present, each axis is serialised; otherwise
    we fall back to the flat ``strengths/weaknesses/reasoning/score``.
    """
    payload: dict[str, Any] = {
        "score": getattr(grade, "score", 0),
        "strengths": list(getattr(grade, "strengths", []) or []),
        "weaknesses": list(getattr(grade, "weaknesses", []) or []),
        "reasoning": getattr(grade, "reasoning", "") or "",
        "error": getattr(grade, "error", "") or "",
    }
    axes = getattr(grade, "axes", None)
    if axes:
        payload["axes"] = {
            name: {
                "score": getattr(axis, "score", 0),
                "strengths": list(getattr(axis, "strengths", []) or []),
                "weaknesses": list(getattr(axis, "weaknesses", []) or []),
                "reasoning": getattr(axis, "reasoning", "") or "",
            }
            for name, axis in axes.items()
        }
    return payload


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Prompt Evaluation Report — {dataset_name}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
            Roboto, sans-serif; line-height: 1.5; margin: 0; padding: 24px;
            color: #1f2933; max-width: 1100px; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 4px; }}
    h2 {{ font-size: 1.2rem; margin-top: 32px; margin-bottom: 8px; }}
    .summary {{ background: #f4f6fa; border-radius: 8px; padding: 16px 20px;
                margin: 16px 0 24px; }}
    .summary span {{ display: inline-block; margin-right: 24px; }}
    .summary strong {{ color: #0b5cad; font-size: 1.4rem; }}
    .case {{ border: 1px solid #d8dde6; border-radius: 6px; padding: 14px 18px;
             margin-bottom: 14px; }}
    .case-head {{ display: flex; justify-content: space-between; align-items: baseline; }}
    .case-id {{ font-family: ui-monospace, "SF Mono", Menlo, monospace; color: #4a5568; }}
    .score {{ font-weight: 600; padding: 2px 8px; border-radius: 4px; }}
    .score-pass {{ background: #d1f7d1; color: #14532d; }}
    .score-fail {{ background: #fde2e1; color: #7f1d1d; }}
    .score-mid {{ background: #fef3c7; color: #78350f; }}
    .reasons li {{ font-size: 0.93rem; }}
    pre {{ background: #f4f6fa; padding: 10px 14px; border-radius: 4px;
           font-size: 0.85rem; overflow-x: auto; white-space: pre-wrap; }}
    .grade-row {{ font-size: 0.9rem; color: #4a5568; }}
    .category {{ display: inline-block; padding: 1px 8px; border-radius: 3px;
                 background: #e8eef9; color: #1d4ed8; font-size: 0.78rem;
                 letter-spacing: 0.02em; margin-left: 8px; vertical-align: middle; }}
  </style>
</head>
<body>
  <h1>Prompt Evaluation Report — {dataset_name}</h1>
  <div class="summary">
    <span><strong>{average:.2f}</strong> average score</span>
    <span><strong>{pass_pct:.0f}%</strong> pass-rate (≥7/10)</span>
    <span>{case_count} cases</span>
    <span>grader: <code>{grader_model}</code></span>
    <span>{started_at}</span>
  </div>
  <h2>Score by category</h2>
  <ul>
{category_list}
  </ul>
  <h2>Per-case results</h2>
{cases}
</body>
</html>
"""


def _render_html(report: EvaluationReport) -> str:
    category_list = "\n".join(
        f"    <li><strong>{html.escape(cat)}</strong>: {score:.2f}</li>"
        for cat, score in sorted(report.score_by_category.items())
    )
    cases_html = "\n".join(_render_case(r) for r in report.results)
    return _HTML_TEMPLATE.format(
        dataset_name=html.escape(report.dataset_name),
        average=report.average_score,
        pass_pct=100.0 * report.pass_rate_at_seven,
        case_count=report.case_count,
        grader_model=html.escape(report.grader_model),
        started_at=html.escape(report.started_at),
        category_list=category_list,
        cases=cases_html,
    )


def _render_case(case: TestCaseResult) -> str:
    score = case.overall_score
    score_class = (
        "score-pass" if score >= 7.0 else "score-fail" if score < 4.0 else "score-mid"
    )
    code_reasons = case.code_grade.reasons_flat()
    weaknesses = case.model_grade.weaknesses
    plan_json = json.dumps(case.plan_payload, indent=2, default=str) if case.plan_payload else "(no plan returned)"
    error_html = (
        f'<p class="grade-row"><strong>grader error:</strong> {html.escape(case.model_grade.error)}</p>'
        if case.model_grade.is_error
        else ""
    )
    return f"""  <div class="case">
    <div class="case-head">
      <div>
        <span class="case-id">{html.escape(case.case_id)}</span>
        <span class="category">{html.escape(case.category)}</span>
      </div>
      <span class="score {score_class}">{score:.2f}/10</span>
    </div>
    <p><strong>goal:</strong> {html.escape(case.goal)}</p>
    <p class="grade-row">
      code: {case.code_grade.overall_score:.2f} · model: {case.model_grade.score} · combined: {case.overall_score:.2f}
    </p>
    {error_html}
    {_render_grade_section("code-grader reasons", code_reasons)}
    {_render_grade_section("model-grader weaknesses", weaknesses)}
    {_render_reasoning(case.model_grade.reasoning)}
    <details><summary>plan payload</summary><pre>{html.escape(plan_json)}</pre></details>
  </div>"""


def _render_grade_section(title: str, items: Iterable[str]) -> str:
    items = [html.escape(s) for s in items if s]
    if not items:
        return ""
    bullets = "\n".join(f"      <li>{s}</li>" for s in items)
    return (
        f'    <p class="grade-row"><strong>{title}:</strong></p>\n'
        f'    <ul class="reasons">\n{bullets}\n    </ul>'
    )


def _render_reasoning(text: str) -> str:
    if not text:
        return ""
    return f'    <p class="grade-row"><strong>reasoning:</strong> {html.escape(text)}</p>'


__all__ = [
    "PromptEvaluator",
    "EvaluationReport",
    "TestCaseResult",
    "RunPromptFunction",
]
