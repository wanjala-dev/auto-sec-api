"""Runner — drives the eval set through the live RAG pipeline.

Two phases, designed so they can run independently:

    collect:  eval_set + live pipeline  →  reports/run-<ts>.json
    score:    reports/run-<ts>.json + judge LLM  →  reports/scored-<ts>.{json,html}

The runner deliberately calls the SAME functions the live chat path
uses — ``_prefetch_retrieved_context`` from ``deep_service`` and
``AgentChatUseCase.execute`` from the agents context — so we're
measuring what the user sees, not a synthetic surrogate.

Cost-control flags:
  * ``--collect-only`` skips judging (no judge LLM calls)
  * ``--score-only`` reads an existing collected run and only scores
  * ``--max-prompts N`` limits the run to the first N prompts
  * ``--only-categories ident,trans`` filters by category

Output naming uses an explicit timestamp passed in by the caller
because ``datetime.now`` is blocked inside the harness for
reproducibility — callers stamp the run name at dispatch time.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ── Run record ────────────────────────────────────────────────────────


@dataclass
class CollectedAnswer:
    """One eval prompt's collected pipeline output.

    `retrieved_chunks` is the prefetch result the planner would see;
    `answer` is what the chat path actually returned. `tool_evidence`
    is the list of (tool, input, output) the agent's ReAct loop
    actually executed during the chat — populated from
    DeepRunLog.tool_observation rows that BaseAgent persists per step.
    All three are written to the run record JSON so scoring can
    replay later without re-running the live pipeline.

    The transactional category (donation_agent.top_donors,
    get_donor_info, etc.) reads the ORM directly and the workspace
    snapshot chunks don't contain those rows; without
    ``tool_evidence`` the Faithfulness judge sees the assistant
    naming dollar amounts and donor names with no supporting
    context and marks every claim unsupported. With it, the judge
    has the same evidence the chat path saw.
    """

    prompt_id: str
    question: str
    category: str
    expected_sections: list[str]
    expected_specialist: str
    reference_answer: str
    retrieved_chunks: list[dict]
    answer: str
    routed_specialists: list[str]
    tool_evidence: list[dict]
    error: str

    def to_dict(self) -> dict:
        return {
            "prompt_id": self.prompt_id,
            "question": self.question,
            "category": self.category,
            "expected_sections": self.expected_sections,
            "expected_specialist": self.expected_specialist,
            "reference_answer": self.reference_answer,
            "retrieved_chunks": self.retrieved_chunks,
            "answer": self.answer,
            "routed_specialists": self.routed_specialists,
            "tool_evidence": self.tool_evidence,
            "error": self.error,
        }


@dataclass
class RunRecord:
    """The persisted collected-phase artifact.

    Versioned so future scorers can detect a schema change instead of
    crashing on a stale record.
    """

    run_id: str
    run_started_at: str
    workspace_uuid: str
    user_uuid: str
    target: str
    answers: list[CollectedAnswer]

    # Bumped to 2 (2026-06-11) when CollectedAnswer gained
    # ``tool_evidence``. The scorer accepts records at v1 (treats
    # tool_evidence as empty) so old runs replay cleanly.
    SCHEMA_VERSION = 2

    def to_dict(self) -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "run_id": self.run_id,
            "run_started_at": self.run_started_at,
            "workspace_uuid": self.workspace_uuid,
            "user_uuid": self.user_uuid,
            "target": self.target,
            "answers": [a.to_dict() for a in self.answers],
        }


# ── Eval set loading ──────────────────────────────────────────────────


def load_eval_set(path: Path) -> list[dict]:
    """Read eval_set.yaml and return the entries list.

    Returns an empty list if the file is missing or malformed — the
    caller logs and exits non-zero. The schema is tolerant: extra
    keys per entry are ignored; missing optional keys default to "".
    """
    if not path.exists():
        logger.error("eval_set not found at %s", path)
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        logger.exception("eval_set parse failed for %s", path)
        return []
    entries = data.get("entries") or []
    normalised: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        normalised.append(
            {
                "id": str(entry.get("id", "")),
                "category": str(entry.get("category", "")),
                "question": str(entry.get("question", "")),
                "expected_sections": list(entry.get("expected_sections") or []),
                "expected_specialist": str(entry.get("expected_specialist") or ""),
                "reference_answer": str(entry.get("reference_answer", "")).strip(),
            }
        )
    return normalised


# ── Collect phase ─────────────────────────────────────────────────────


def collect(
    *,
    cfg,
    run_id: str,
    eval_entries: list[dict],
) -> RunRecord:
    """Drive every eval entry through the live RAG + chat pipeline.

    For each entry:
      1. Run ``_prefetch_retrieved_context(workspace_id, goal)`` — same
         call the planner makes during a real chat.
      2. Run the chat path via ``AgentChatUseCase.execute`` so we get
         the answer the user would actually see.
      3. Stash both in a ``CollectedAnswer``.

    Errors per-entry are captured into ``CollectedAnswer.error`` so a
    bad row doesn't kill the whole run.
    """
    # Lazy imports keep the harness module importable without Django.
    # Tests for the metrics use only judge/metrics; they don't trigger
    # this codepath, so they don't need Django either.
    import django

    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        os.environ["DJANGO_SETTINGS_MODULE"] = "api.settings.local"
    django.setup()

    from components.agents.application.commands.agent_chat_command import (
        AgentChatCommand,
    )
    from components.agents.application.providers.ai_provider import AIProvider
    from components.agents.infrastructure.services.deep_service import (
        _prefetch_retrieved_context,
    )

    answers: list[CollectedAnswer] = []
    use_case = AIProvider.build_agent_chat_use_case()

    # Look up the eval user's actual persona in the eval workspace.
    # AgentChatCommand defaults to "contributor" (100 messages/day),
    # which silently zeroed the 2026-06-11 narrative-chunks baseline
    # by rejecting every prompt on quota.  Using the real membership
    # persona means an owner / admin runs unlimited.
    persona_role = _persona_for_membership(
        workspace_uuid=cfg.workspace_uuid, user_uuid=cfg.user_uuid
    )
    logger.info(
        "collect using persona_role=%s for user_uuid=%s",
        persona_role,
        cfg.user_uuid,
    )

    for entry in eval_entries:
        question = entry["question"]
        prompt_id = entry["id"]
        logger.info("collect prompt_id=%s question=%r", prompt_id, question)

        try:
            chunks = _prefetch_retrieved_context(
                workspace_id=cfg.workspace_uuid,
                goal=question,
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("prefetch failed prompt_id=%s", prompt_id)
            chunks = []
            error = f"prefetch_error: {exc}"
        else:
            error = ""

        chat_answer = ""
        routed_specialists: list[str] = []
        tool_evidence: list[dict] = []
        try:
            from uuid import UUID

            command = AgentChatCommand(
                query=question,
                workspace_id=UUID(cfg.workspace_uuid),
                user_id=UUID(cfg.user_uuid),
                agent_type="ai_teammate",
                persona_role=persona_role,
            )
            result = use_case.execute(command)
            chat_answer = getattr(result, "response", "") or ""
            plan_id = getattr(result, "plan_id", "") or ""
            # Capture which specialists the planner actually routed
            # to from the persisted DeepRun.state. Used by the
            # routing-accuracy aggregate. AgentChatSuccess doesn't
            # expose routed_specialists directly, so we look it up.
            if plan_id:
                routed_specialists = _routed_specialists_for(plan_id)
                tool_evidence = _tool_evidence_for(plan_id)
            # AgentChatFailure stores the reason in ``error`` (not an
            # exception path).  Surface it so we don't silently score
            # 30/30 empty answers as 0.0 and think the model broke
            # when it's actually a quota / entitlement refusal.
            failure_reason = getattr(result, "error", "") or ""
            if failure_reason and not chat_answer:
                error = (error + " " if error else "") + (
                    f"chat_refused: {failure_reason}"
                )
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("chat failed prompt_id=%s", prompt_id)
            error = (error + " " if error else "") + f"chat_error: {exc}"

        answers.append(
            CollectedAnswer(
                prompt_id=prompt_id,
                question=question,
                category=entry["category"],
                expected_sections=entry["expected_sections"],
                expected_specialist=entry["expected_specialist"],
                reference_answer=entry["reference_answer"],
                retrieved_chunks=[_chunk_to_dict(c) for c in chunks],
                answer=chat_answer,
                routed_specialists=routed_specialists,
                tool_evidence=tool_evidence,
                error=error,
            )
        )

    return RunRecord(
        run_id=run_id,
        run_started_at=_now_iso(),
        workspace_uuid=cfg.workspace_uuid,
        user_uuid=cfg.user_uuid,
        target=cfg.target,
        answers=answers,
    )


def _persona_for_membership(*, workspace_uuid: str, user_uuid: str) -> str:
    """Look up the eval user's persona in the eval workspace.

    Falls back to ``admin`` rather than ``contributor`` when no
    membership row is found.  Rationale: the eval workspace is
    expected to have an owner-role user wired up; if it doesn't,
    the right failure mode is the eval running unlimited (admin
    persona has ``max_messages_per_day=0`` ≡ unlimited per the
    default WorkspaceAIConfig persona_limits) rather than hitting
    the 100/day contributor cap and silently zeroing every prompt.

    The 2026-06-11 narrative-chunks A/B hit this exact silent
    failure — every prompt got refused with HTTP 403 "Daily
    message limit reached (100 messages)" and the eval scored
    them all as 0.0 / 0.0 / 0.0 across Faithfulness, Answer
    Relevancy, Routing Accuracy.  The retrieval-side metrics
    (Precision, Recall) still measured correctly because chunks
    are captured before the chat path even runs.

    Returns the persona slug as the chat command expects it.
    """
    try:
        from infrastructure.persistence.workspaces.models import (
            WorkspaceMembership,
        )

        membership = (
            WorkspaceMembership.objects.filter(
                workspace_id=workspace_uuid,
                user_id=user_uuid,
            )
            .only("persona")
            .first()
        )
        if membership and membership.persona:
            return str(membership.persona)
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "failed to look up persona for eval user "
            "workspace_uuid=%s user_uuid=%s",
            workspace_uuid,
            user_uuid,
        )
    return "admin"


def _tool_evidence_for(plan_id: str) -> list[dict]:
    """Pull the tool observations the deep-run executor persisted.

    Reads every ``DeepRunLog.event_type='tool_observation'`` row
    written by ``BaseAgent._persist_tool_observations`` during the
    chat run and returns them in chronological order.

    Each row carries ``{tool_input, tool_output, truncated_input,
    truncated_output}`` in its payload and ``tool_name`` /
    ``agent_type`` as direct columns; we flatten the four fields a
    metric actually reads into a dict and drop the rest. The order
    matters: the Faithfulness judge sees them in the order the
    agent ran them, mirroring the LLM's own intermediate-step trail.

    Returns an empty list on any lookup failure — a metric that
    relies on tool evidence will then degrade to "no supporting
    evidence" rather than crashing the run. That's the same
    failure mode as ``_routed_specialists_for``.
    """
    try:
        from infrastructure.persistence.ai.agents.models import (
            DeepRun,
            DeepRunLog,
        )

        run = DeepRun.objects.filter(plan_id=plan_id).first()
        if run is None:
            return []
        rows = (
            DeepRunLog.objects.filter(
                deep_run=run, event_type="tool_observation"
            )
            .order_by("created_at")
            .values("agent_type", "tool_name", "payload")
        )
        evidence: list[dict] = []
        for row in rows:
            payload = row.get("payload") or {}
            evidence.append(
                {
                    "agent_type": row.get("agent_type") or "",
                    "tool_name": row.get("tool_name") or "",
                    "tool_input": payload.get("tool_input") or "",
                    "tool_output": payload.get("tool_output") or "",
                    "truncated_input": bool(
                        payload.get("truncated_input")
                    ),
                    "truncated_output": bool(
                        payload.get("truncated_output")
                    ),
                }
            )
        return evidence
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "failed to look up tool evidence plan_id=%s", plan_id
        )
        return []


def _routed_specialists_for(plan_id: str) -> list[str]:
    """Pull the planner's chosen specialists for ``plan_id``.

    Reads ``DeepRun.state["plan"]["tasks"][*].agent_type`` so a
    multi-route emit shows up as multiple entries. Returns an empty
    list on any lookup failure — routing accuracy treats that as a
    miss rather than crashing the run.
    """
    try:
        from infrastructure.persistence.ai.agents.models import DeepRun

        run = DeepRun.objects.filter(plan_id=plan_id).first()
        if run is None:
            return []
        state = run.state or {}
        plan = state.get("plan") or {}
        tasks = plan.get("tasks") or []
        return [
            str(t.get("agent_type") or "")
            for t in tasks
            if isinstance(t, dict) and t.get("agent_type")
        ]
    except Exception:  # pylint: disable=broad-except
        logger.exception(
            "failed to look up routed specialists plan_id=%s", plan_id
        )
        return []


def _chunk_to_dict(chunk) -> dict:
    """Normalise a retrieved chunk to a JSON-serializable dict.

    ``_prefetch_retrieved_context`` returns plain dicts already
    (section/section_title/content/score) — keep that shape but be
    defensive about future drift.
    """
    if isinstance(chunk, dict):
        return {
            "content": chunk.get("content", "") or "",
            "metadata": {"section": chunk.get("section", "") or ""},
            "score": chunk.get("score", 0.0),
        }
    # Fallback for object shapes
    return {
        "content": getattr(chunk, "content", "") or "",
        "metadata": {
            "section": (getattr(chunk, "metadata", {}) or {}).get("section", "")
        },
        "score": getattr(chunk, "score", 0.0),
    }


def _now_iso() -> str:
    """Wall-clock ISO timestamp — only used in run metadata.

    Eval runs are inherently non-deterministic (real LLM calls), so
    the timestamp in the run record is informational, not a freshness
    invariant.
    """
    return datetime.now(UTC).isoformat()


# ── CLI ───────────────────────────────────────────────────────────────


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rag-eval-runner",
        description="Run the RAG eval harness against the live pipeline.",
    )
    parser.add_argument(
        "--run-id",
        required=True,
        help="Identifier for this run, used in the output filename.",
    )
    parser.add_argument(
        "--phase",
        choices=("collect", "score", "all"),
        default="all",
        help=(
            "collect = run the pipeline only; score = judge an existing "
            "run record; all = collect then score in one invocation."
        ),
    )
    parser.add_argument(
        "--max-prompts",
        type=int,
        default=0,
        help="Limit run to the first N prompts (0 = all).",
    )
    parser.add_argument(
        "--only-categories",
        default="",
        help="Comma-separated category filter (empty = all).",
    )
    parser.add_argument(
        "--replay-run-path",
        type=Path,
        default=None,
        help="Path to a previously-collected run record (for --phase score).",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)

    from tests.eval.rag import config as cfg_mod

    cfg = cfg_mod.load()
    eval_entries = load_eval_set(cfg.eval_set_path)
    if not eval_entries:
        logger.error("eval set empty; nothing to do")
        return 1

    if args.only_categories:
        wanted = {c.strip() for c in args.only_categories.split(",") if c.strip()}
        eval_entries = [e for e in eval_entries if e["category"] in wanted]
    if args.max_prompts > 0:
        eval_entries = eval_entries[: args.max_prompts]

    cfg.reports_dir.mkdir(parents=True, exist_ok=True)

    if args.phase in ("collect", "all"):
        record = collect(cfg=cfg, run_id=args.run_id, eval_entries=eval_entries)
        out_path = cfg.reports_dir / f"run-{args.run_id}.json"
        out_path.write_text(
            json.dumps(record.to_dict(), indent=2),
            encoding="utf-8",
        )
        logger.info("collect phase wrote %s (%d answers)", out_path, len(record.answers))

    if args.phase in ("score", "all"):
        # Score phase is intentionally separate so it can be re-run
        # cheaply on an existing collected record. See scorer.py for
        # the implementation; this stub keeps the runner CLI symmetric
        # while the scorer module lands.
        logger.info("score phase: invoking tests.eval.rag.scorer")
        from tests.eval.rag import scorer

        run_path = (
            args.replay_run_path
            or cfg.reports_dir / f"run-{args.run_id}.json"
        )
        scorer.score_run(cfg=cfg, run_id=args.run_id, run_record_path=run_path)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
