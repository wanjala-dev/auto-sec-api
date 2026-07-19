"""Promote thumbs-down ``AgentResponseFeedback`` rows into an eval dataset.

Wave 4 of the prompt-evaluation plan
(``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``). The
user's real failure cases are the highest-signal eval inputs the
Logseq curriculum talks about — every thumbs-down on an assistant
message is a case the prompt got wrong from a real human's
perspective. This command turns those rows into candidate cases on a
named eval dataset, ready for hand-review and promotion.

Usage:

.. code-block:: shell

    # Append every new thumbs-down to the planner dataset, dry-run first.
    python manage.py promote_feedback_to_dataset \\
        --dataset planner_v1 --dry-run

    # Actually write.
    python manage.py promote_feedback_to_dataset --dataset planner_v1

    # Window the import to the last 7 days.
    python manage.py promote_feedback_to_dataset \\
        --dataset planner_v1 --since 7d

    # Limit to a workspace.
    python manage.py promote_feedback_to_dataset \\
        --dataset planner_v1 --workspace-id <uuid>

What "candidate case" means: each entry on the dataset has
``id`` (``feedback-<feedback_uuid>``), ``goal`` (the user message
that produced the response), ``context`` (the captured RAG /
conversation-history snippet from the matching ``DeepRunLog`` row if
one exists), and ``feedback`` (the rating + optional comment). The
``expected`` block is intentionally left empty — a human reviewer
fills it in before promoting the case to a graded test.

Idempotency: the writer skips any feedback id already present on
the dataset. Re-running is safe.

Failure modes:
* Feedback row with no matching ``DeepRunLog`` — the LLM call that
  produced the response wasn't instrumented (rare; pre-Wave-1
  conversation). Included with an empty ``context`` so the case is
  still actionable.
* Feedback row on a non-assistant message — silently skipped (only
  assistant messages can have meaningful eval cases attached to them;
  thumbs-down on a human message is a user-error and we just ignore).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError


_SINCE_RE = re.compile(r"^(\d+)([dhm])$")
_DEFAULT_DATASET_DIR = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "prompt_eval"
    / "datasets"
)


def _parse_since(spec: str | None) -> datetime | None:
    """Parse ``7d`` / ``24h`` / ``30m`` into a UTC cutoff datetime."""
    if not spec:
        return None
    match = _SINCE_RE.match(spec)
    if not match:
        raise CommandError(
            f"--since must look like '7d' / '24h' / '30m'; got {spec!r}"
        )
    amount = int(match.group(1))
    unit = match.group(2)
    delta_map = {"d": timedelta(days=1), "h": timedelta(hours=1), "m": timedelta(minutes=1)}
    return datetime.now(timezone.utc) - amount * delta_map[unit]


def _resolve_dataset_path(dataset: str, override: str) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_DATASET_DIR / f"{dataset}.json"


def _load_dataset(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"_meta": {"name": path.stem}, "cases": []}
    return json.loads(path.read_text())


def _existing_feedback_ids(dataset: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for case in dataset.get("cases") or ():
        case_id = str(case.get("id") or "")
        if case_id.startswith("feedback-"):
            ids.add(case_id[len("feedback-"):])
    return ids


def _build_candidate(
    *,
    feedback,
    message,
    user_message,
    deep_run_log,
) -> dict[str, Any]:
    """Build the dataset entry. Leaves ``expected`` empty for human review."""
    context: dict[str, Any] = {}
    if deep_run_log is not None:
        payload = deep_run_log.payload or {}
        if isinstance(payload, dict):
            for key in ("retrieved_context", "conversation_history",
                        "workspace_profile"):
                if key in payload:
                    context[key] = payload[key]
    return {
        "id": f"feedback-{feedback.id}",
        "source": "agent_response_feedback",
        "goal": (user_message.content if user_message is not None else "")[:4000],
        "context": context,
        "feedback": {
            "rating": feedback.rating,
            "comment": feedback.comment or "",
            "user_id": str(feedback.user_id) if feedback.user_id else None,
            "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
        },
        "captured_response": (message.content or "")[:4000],
        "expected": {},
    }


class Command(BaseCommand):
    help = (
        "Append thumbs-down AgentResponseFeedback rows to an eval "
        "dataset as candidate cases for hand-review."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset", required=True,
            help=(
                "Dataset slug — resolves to "
                "components/agents/tests/prompt_eval/datasets/<slug>.json. "
                "Created if it doesn't exist."
            ),
        )
        parser.add_argument(
            "--dataset-path", dest="dataset_path", default="",
            help="Absolute path override for the dataset JSON.",
        )
        parser.add_argument(
            "--since", default=None,
            help="Window the import (e.g. '7d', '24h', '30m').",
        )
        parser.add_argument(
            "--workspace-id", dest="workspace_id", default=None,
            help="Limit to feedback on conversations in one workspace.",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Cap the number of new cases added (0 = no cap).",
        )
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true",
            help="Print the candidates that would be appended; do not write.",
        )

    def handle(self, *args, **options):
        from infrastructure.persistence.ai.agents.models import DeepRunLog
        from infrastructure.persistence.ai.conversations.models import (
            AgentResponseFeedback,
            ConversationMessage,
        )

        dataset_slug = options["dataset"]
        dataset_path = _resolve_dataset_path(
            dataset_slug, options.get("dataset_path") or ""
        )
        since = _parse_since(options.get("since"))
        workspace_id = options.get("workspace_id")
        limit = max(0, int(options.get("limit") or 0))
        dry_run = bool(options.get("dry_run"))

        dataset = _load_dataset(dataset_path)
        existing = _existing_feedback_ids(dataset)

        queryset = AgentResponseFeedback.objects.filter(
            rating=AgentResponseFeedback.RATING_DOWN,
        ).select_related("message", "message__conversation").order_by("created_at")
        if since is not None:
            queryset = queryset.filter(created_at__gte=since)
        if workspace_id:
            queryset = queryset.filter(
                message__conversation__metadata__workspace_id=workspace_id,
            )

        new_cases: list[dict[str, Any]] = []
        skipped_duplicate = 0
        skipped_non_assistant = 0
        skipped_no_user_turn = 0

        for feedback in queryset.iterator():
            if str(feedback.id) in existing:
                skipped_duplicate += 1
                continue
            message = feedback.message
            if message.role != "assistant":
                skipped_non_assistant += 1
                continue
            user_message = (
                ConversationMessage.objects
                .filter(
                    conversation_id=message.conversation_id,
                    role="human",
                    created_at__lt=message.created_at,
                )
                .order_by("-created_at")
                .first()
            )
            if user_message is None:
                skipped_no_user_turn += 1
                continue
            # DeepRun has ``thread_id`` (CharField), not a FK to
            # Conversation. The chat path uses the conversation UUID as
            # the thread_id string. Match on that; gracefully fall back
            # to no DeepRunLog when the deep run wasn't captured.
            deep_run_log = (
                DeepRunLog.objects
                .filter(
                    event_type="llm_call",
                    deep_run__thread_id=str(message.conversation_id),
                )
                .order_by("-created_at")
                .first()
            )
            new_cases.append(_build_candidate(
                feedback=feedback,
                message=message,
                user_message=user_message,
                deep_run_log=deep_run_log,
            ))
            if limit and len(new_cases) >= limit:
                break

        if dry_run:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"DRY RUN — would append {len(new_cases)} case(s) to "
                f"{dataset_path}"
            ))
            for case in new_cases[:5]:
                self.stdout.write(json.dumps(case, indent=2)[:600] + "\n...")
            self.stdout.write(self.style.SUCCESS(self._summary(
                added=len(new_cases),
                skipped_duplicate=skipped_duplicate,
                skipped_non_assistant=skipped_non_assistant,
                skipped_no_user_turn=skipped_no_user_turn,
                dataset_path=dataset_path,
                dry_run=True,
            )))
            return

        if new_cases:
            cases = list(dataset.get("cases") or [])
            cases.extend(new_cases)
            dataset["cases"] = cases
            meta = dict(dataset.get("_meta") or {})
            meta["case_count"] = len(cases)
            meta["last_promoted_at"] = datetime.now(timezone.utc).isoformat()
            dataset["_meta"] = meta
            dataset_path.parent.mkdir(parents=True, exist_ok=True)
            dataset_path.write_text(json.dumps(dataset, indent=2) + "\n")

        self.stdout.write(self.style.SUCCESS(self._summary(
            added=len(new_cases),
            skipped_duplicate=skipped_duplicate,
            skipped_non_assistant=skipped_non_assistant,
            skipped_no_user_turn=skipped_no_user_turn,
            dataset_path=dataset_path,
            dry_run=False,
        )))

    @staticmethod
    def _summary(*, added, skipped_duplicate, skipped_non_assistant,
                 skipped_no_user_turn, dataset_path, dry_run):
        verb = "Would append" if dry_run else "Appended"
        return (
            f"{verb} {added} case(s) to {dataset_path}. "
            f"Skipped {skipped_duplicate} duplicate(s), "
            f"{skipped_non_assistant} non-assistant message(s), "
            f"{skipped_no_user_turn} feedback row(s) with no user turn."
        )
