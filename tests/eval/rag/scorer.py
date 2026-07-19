"""Scorer — judges a collected run record against the four RAGAS metrics.

Reads a ``run-<id>.json`` file produced by ``runner.collect`` and
writes ``scored-<id>.json`` plus ``scored-<id>.html`` with per-prompt
metrics + aggregates.

The judge LLM is the OpenAI provider via our existing
``AILlmProvider`` port — runner-side, scorer-side, anywhere we need a
LLM call goes through the same port so swapping providers is one
config change.

The scorer is intentionally tolerant: a single bad judge response
zeroes that one metric for that one prompt, but the run still produces
a report. Use the per-prompt detail in the HTML to debug specific
failures.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests.eval.rag import report as report_mod
from tests.eval.rag.judge import CachedJudge, Judge, JudgeRequest
from tests.eval.rag.metrics import (
    AnswerRelevancy,
    ContextPrecision,
    ContextRecall,
    Faithfulness,
    MetricResult,
)

logger = logging.getLogger(__name__)


# ── Judge implementation via our LLM provider port ────────────────────


class LLMProviderJudge:
    """Calls the configured LLM provider via ``AILlmProvider``.

    Lazy import keeps the scorer module importable without Django so
    the metric unit tests can keep their fast collection path.
    """

    def __init__(self, model: str, temperature: float, max_tokens: int):
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._llm = None

    def _llm_port(self):
        if self._llm is None:
            from components.knowledge.application.providers.ai_llm_provider import (
                AILlmProvider,
            )

            self._llm = AILlmProvider().get_default_port()
        return self._llm

    def call(self, request: JudgeRequest) -> str:
        port = self._llm_port()
        try:
            response = port.chat(
                messages=[
                    {"role": "system", "content": request.system},
                    {"role": "user", "content": request.user},
                ],
                model=self._model,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except Exception:  # pylint: disable=broad-except
            logger.exception(
                "judge LLM call failed prompt_id=%s", request.prompt_id
            )
            return ""
        # LlmResponse exposes .content; fall back to str() for any
        # adapter that diverges from the port contract.
        content = getattr(response, "content", None)
        if content is not None:
            return str(content)
        if isinstance(response, dict):
            return response.get("content") or response.get("text") or ""
        return str(response) if response is not None else ""


# ── Scored result containers ──────────────────────────────────────────


@dataclass
class ScoredEntry:
    prompt_id: str
    question: str
    category: str
    expected_specialist: str
    routed_specialists: list[str]
    answer: str
    error: str
    metrics: dict[str, MetricResult]
    retrieved_chunks_count: int

    def to_dict(self) -> dict:
        return {
            "prompt_id": self.prompt_id,
            "question": self.question,
            "category": self.category,
            "expected_specialist": self.expected_specialist,
            "routed_specialists": self.routed_specialists,
            "answer": self.answer,
            "error": self.error,
            "retrieved_chunks_count": self.retrieved_chunks_count,
            "metrics": {
                name: {"score": m.score, "detail": m.detail}
                for name, m in self.metrics.items()
            },
        }


@dataclass
class ScoredRun:
    run_id: str
    run_started_at: str
    workspace_uuid: str
    target: str
    entries: list[ScoredEntry]

    def aggregates(self) -> dict[str, float]:
        """Mean per metric across all scored entries.

        Empty runs return 0.0 for every metric — better than NaN that
        breaks JSON serialization. Routing accuracy is a sixth aggregate
        outside the four RAGAS metrics.
        """
        if not self.entries:
            return {
                "faithfulness": 0.0,
                "answer_relevancy": 0.0,
                "context_precision": 0.0,
                "context_recall": 0.0,
                "routing_accuracy": 0.0,
            }
        metric_names = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
        aggregated: dict[str, float] = {}
        for name in metric_names:
            scores = [e.metrics[name].score for e in self.entries if name in e.metrics]
            aggregated[name] = sum(scores) / len(scores) if scores else 0.0
        # Routing accuracy: fraction of prompts where the planner
        # routed to the expected specialist. Prompts with
        # expected_specialist=="" are skipped (multi-route / clarify
        # cases). Prompts that emit multiple tasks score 1.0 if the
        # expected specialist is anywhere in the routed list.
        considered = [e for e in self.entries if e.expected_specialist]
        if considered:
            hits = sum(
                1
                for e in considered
                if e.expected_specialist in (e.routed_specialists or [])
                or e.expected_specialist == "clarify"
            )
            aggregated["routing_accuracy"] = hits / len(considered)
        else:
            aggregated["routing_accuracy"] = 0.0
        return aggregated

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "run_id": self.run_id,
            "run_started_at": self.run_started_at,
            "workspace_uuid": self.workspace_uuid,
            "target": self.target,
            "aggregates": self.aggregates(),
            "entries": [e.to_dict() for e in self.entries],
        }


# ── Scoring pass ──────────────────────────────────────────────────────


def score_run(*, cfg, run_id: str, run_record_path: Path) -> ScoredRun:
    """Read a collected run record and produce a ScoredRun.

    Each entry is scored with the four metrics; errors are recorded
    per-entry so a single bad row doesn't blow up the run.
    """
    record = json.loads(run_record_path.read_text(encoding="utf-8"))
    schema_version = record.get("schema_version")
    if schema_version not in (1, 2):
        raise RuntimeError(
            f"Unsupported run record schema: {schema_version!r}. "
            "Re-collect the run with the current runner."
        )

    judge: Judge = LLMProviderJudge(
        model=cfg.judge_model,
        temperature=cfg.judge_temperature,
        max_tokens=cfg.judge_max_tokens,
    )
    judge = CachedJudge(judge, cfg.judge_cache_path)

    faithfulness = Faithfulness(
        judge_model=cfg.judge_model, judge_temperature=cfg.judge_temperature
    )
    answer_relevancy = AnswerRelevancy(
        judge_model=cfg.judge_model, judge_temperature=cfg.judge_temperature
    )
    context_precision = ContextPrecision(
        judge_model=cfg.judge_model, judge_temperature=cfg.judge_temperature
    )
    context_recall = ContextRecall()

    scored_entries: list[ScoredEntry] = []
    for entry in record.get("answers", []):
        chunks = entry.get("retrieved_chunks") or []
        # Tool evidence absent in schema v1 records — treat as empty
        # so old runs still score cleanly. New runs (v2+) carry the
        # observations the ReAct executor produced; Faithfulness
        # reads them so transactional answers backed by ORM tool
        # calls (donation_agent, financial_agent) don't get marked
        # unsupported just because the snapshot chunks didn't carry
        # the figures.
        tool_evidence = entry.get("tool_evidence") or []
        metrics: dict[str, MetricResult] = {}
        try:
            metrics["faithfulness"] = faithfulness.score(
                prompt_id=entry["prompt_id"],
                answer=entry["answer"],
                retrieved_chunks=chunks,
                tool_evidence=tool_evidence,
                judge=judge,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("faithfulness failed prompt_id=%s", entry["prompt_id"])
            metrics["faithfulness"] = MetricResult(
                name="faithfulness", score=0.0, detail={"error": str(exc)}
            )

        try:
            metrics["answer_relevancy"] = answer_relevancy.score(
                prompt_id=entry["prompt_id"],
                question=entry["question"],
                answer=entry["answer"],
                judge=judge,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("answer_relevancy failed prompt_id=%s", entry["prompt_id"])
            metrics["answer_relevancy"] = MetricResult(
                name="answer_relevancy", score=0.0, detail={"error": str(exc)}
            )

        try:
            metrics["context_precision"] = context_precision.score(
                prompt_id=entry["prompt_id"],
                question=entry["question"],
                retrieved_chunks=chunks,
                judge=judge,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("context_precision failed prompt_id=%s", entry["prompt_id"])
            metrics["context_precision"] = MetricResult(
                name="context_precision", score=0.0, detail={"error": str(exc)}
            )

        try:
            metrics["context_recall"] = context_recall.score(
                prompt_id=entry["prompt_id"],
                expected_sections=entry.get("expected_sections", []),
                retrieved_chunks=chunks,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("context_recall failed prompt_id=%s", entry["prompt_id"])
            metrics["context_recall"] = MetricResult(
                name="context_recall", score=0.0, detail={"error": str(exc)}
            )

        scored_entries.append(
            ScoredEntry(
                prompt_id=entry["prompt_id"],
                question=entry["question"],
                category=entry["category"],
                expected_specialist=entry.get("expected_specialist", ""),
                routed_specialists=entry.get("routed_specialists", []),
                answer=entry["answer"],
                error=entry.get("error", ""),
                metrics=metrics,
                retrieved_chunks_count=len(chunks),
            )
        )

    scored = ScoredRun(
        run_id=run_id,
        run_started_at=record.get("run_started_at", ""),
        workspace_uuid=record.get("workspace_uuid", ""),
        target=record.get("target", ""),
        entries=scored_entries,
    )

    report_mod.write_reports(scored=scored, reports_dir=cfg.reports_dir)
    return scored


# ── CLI entry ─────────────────────────────────────────────────────────


def main(argv: list[str]) -> int:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="rag-eval-scorer")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--run-record-path",
        type=Path,
        required=True,
        help="Path to the collected run record JSON.",
    )
    args = parser.parse_args(argv)

    from tests.eval.rag import config as cfg_mod

    cfg = cfg_mod.load()
    score_run(cfg=cfg, run_id=args.run_id, run_record_path=args.run_record_path)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main(sys.argv[1:]))
