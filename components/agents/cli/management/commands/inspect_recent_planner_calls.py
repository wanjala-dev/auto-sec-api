"""Inspect recent planner LLM calls — developer microscope for prompt iteration.

When a chat answer is wrong, this command lets a developer read the actual
prompt the planner sent, the model's response, and the cost of the call —
without having to attach a debugger or wade through worker logs.

Reads from ``DeepRunLog`` rows of type ``llm_call`` written by
``components.agents.infrastructure.adapters.langchain.deep.llm_planner._log_llm_call``.
The instrumentation is opt-in (it logs only when the planner ran inside
a real ``DeepRun``), so this command shows production / dev-server
traffic but skips ad-hoc CLI invocations.

Plan reference: ``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``
Wave 1, step 2C.
"""
from __future__ import annotations

from typing import Any, Iterable

from django.core.management.base import BaseCommand
from django.utils import timezone


def _truncate(text: str, max_len: int) -> str:
    """Truncate ``text`` to ``max_len`` characters with an ellipsis suffix.

    Plan iteration usually only needs the head and tail of long strings;
    callers can opt out by passing ``--full``.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"… [truncated {len(text) - max_len} chars]"


def _format_cost(cost: Any) -> str:
    if cost is None:
        return "—"
    try:
        return f"${cost:.6f}"
    except (TypeError, ValueError):
        return str(cost)


def _format_tokens(prompt: Any, completion: Any) -> str:
    if prompt is None and completion is None:
        return "—"
    parts: list[str] = []
    if prompt is not None:
        parts.append(f"in={prompt}")
    if completion is not None:
        parts.append(f"out={completion}")
    return " ".join(parts)


def _iter_log_rows(*, limit: int, workspace_id: str | None):
    from infrastructure.persistence.ai.agents.models import DeepRunLog

    queryset = (
        DeepRunLog.objects.filter(event_type="llm_call")
        .select_related("deep_run", "deep_run__workspace", "deep_run__user")
        .order_by("-created_at")
    )
    if workspace_id:
        queryset = queryset.filter(deep_run__workspace_id=workspace_id)
    return list(queryset[:limit])


class Command(BaseCommand):
    """Print the last N planner LLM calls in human-readable form."""

    help = (
        "Print the last N planner LLM calls (system prompt, user prompt, "
        "response, tokens, latency, cost) so a developer can iterate on "
        "prompts using real production traffic."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Number of most-recent calls to show (default: 5).",
        )
        parser.add_argument(
            "--workspace-id",
            dest="workspace_id",
            type=str,
            default=None,
            help="Limit to calls from a specific workspace UUID.",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help=(
                "Show the full prompt and response without truncating. "
                "Default truncates at 1200 chars per field for readability."
            ),
        )

    def handle(self, *args, **options):
        limit = max(1, int(options.get("limit") or 5))
        workspace_id = options.get("workspace_id")
        full = bool(options.get("full"))
        max_len = 1_000_000 if full else 1_200

        rows: Iterable[Any] = _iter_log_rows(limit=limit, workspace_id=workspace_id)
        rows = list(rows)

        if not rows:
            self.stdout.write(
                self.style.WARNING(
                    "No DeepRunLog rows of event_type='llm_call' found. "
                    "Either no planner runs have happened yet, or the "
                    "instrumentation in `llm_planner._log_llm_call` is not "
                    "writing rows (e.g. no matching DeepRun row exists for "
                    "the plan_id)."
                )
            )
            return

        scope = (
            f" for workspace {workspace_id}" if workspace_id else ""
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Last {len(rows)} planner LLM calls{scope} "
                f"(now: {timezone.now().isoformat()}):\n"
            )
        )

        for index, row in enumerate(rows, start=1):
            run = row.deep_run
            workspace_label = (
                str(getattr(run, "workspace_id", "—")) if run else "—"
            )
            user_label = (
                str(getattr(run, "user_id", "—")) if run else "—"
            )
            divider = "─" * 78

            self.stdout.write(divider)
            self.stdout.write(
                self.style.MIGRATE_HEADING(
                    f"#{index}  plan_id={getattr(run, 'plan_id', '—')}  "
                    f"workspace={workspace_label}  user={user_label}"
                )
            )
            self.stdout.write(
                f"    when:        {row.created_at.isoformat()}"
            )
            self.stdout.write(
                f"    model:       {row.model_used or '—'}"
            )
            self.stdout.write(
                f"    tokens:      {_format_tokens(row.prompt_tokens, row.completion_tokens)}"
            )
            self.stdout.write(
                f"    latency:     {row.latency_ms or '—'} ms"
            )
            self.stdout.write(
                f"    cost:        {_format_cost(row.cost_usd)}"
            )
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("    [system prompt]"))
            self.stdout.write(_truncate(row.system_prompt or "", max_len))
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("    [user prompt]"))
            self.stdout.write(_truncate(row.user_prompt or "", max_len))
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("    [llm response]"))
            self.stdout.write(_truncate(row.llm_response or "", max_len))
            self.stdout.write("")

        self.stdout.write("─" * 78)
        self.stdout.write(
            self.style.SUCCESS(
                f"Showed {len(rows)} call(s). Use --limit N to see more, "
                "--workspace-id <uuid> to filter, --full to disable truncation."
            )
        )
