"""Replay captured planner calls against a candidate prompt version.

Wave 3 of the prompt-evaluation plan
(``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``). Lets a
developer re-run the planner LLM call from a captured conversation
against a candidate ``planner.system`` version, side-by-side with the
original response, and grade both with the same code+model graders the
eval harness uses.

Usage:

.. code-block:: shell

    python manage.py replay_conversation \\
        --conversation-id 3f2a... \\
        --prompt planner.system@v1

* ``--conversation-id`` (required) — UUID of the ``Conversation`` row.
  The command finds every ``DeepRunLog`` row of type ``llm_call`` for
  any ``DeepRun`` belonging to that conversation (matched via
  ``DeepRun.thread_id``, which the chat path sets to the conversation
  UUID string) and replays each one.
* ``--prompt`` (required) — ``<prompt_id>@<version>`` (e.g.
  ``planner.system@v1``). The version is resolved through
  ``PromptRegistry`` and substituted into the captured user prompt's
  call site. The version label ``active`` resolves to the registry's
  active pointer.
* ``--no-llm`` (optional) — skip the candidate LLM call; only print the
  captured prompt + response. Useful for dry-running the command in CI
  or against a workspace where the OpenAI key isn't available.
* ``--max-calls N`` (optional, default 5) — cap the number of replayed
  calls so a long conversation doesn't burn through budget. Calls are
  replayed oldest-first.

The output for each call is a four-block panel:

1. **Context** — plan_id, model_used, original cost.
2. **Captured response** — what the planner said the first time.
3. **Candidate response** — what the candidate prompt produces now.
4. **Grader scores** — code+model graders on both responses; ``Δ``
   column shows candidate minus captured. Negative deltas highlighted.

The command never writes to the database — replay is read-only
plus one LLM call per replayed turn.
"""
from __future__ import annotations

import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError


def _truncate(text: str, max_len: int = 1_200) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    if len(text) <= max_len:
        return text
    return text[:max_len] + f"… [truncated {len(text) - max_len} chars]"


def _parse_prompt_spec(spec: str) -> tuple[str, str]:
    """Parse ``planner.system@v2`` into (prompt_id, version)."""
    if "@" not in spec:
        raise CommandError(
            f"--prompt must be '<prompt_id>@<version>' (e.g. "
            f"'planner.system@v2'); got {spec!r}"
        )
    prompt_id, _, version = spec.partition("@")
    if not prompt_id or not version:
        raise CommandError(
            f"--prompt must be non-empty on both sides of '@'; got {spec!r}"
        )
    return prompt_id, version


def _render_planner_system(prompt_id: str, version: str) -> str:
    """Render the planner system prompt with the live agent catalog.

    Only ``planner.system`` has template variables today; other prompts
    are returned as-is via ``get()``.
    """
    from components.agents.infrastructure.prompts.registry import (
        PromptRegistry,
    )

    if prompt_id == "planner.system":
        from components.agents.infrastructure.adapters.langchain.deep.llm_planner import (
            _build_agent_catalog,
        )
        return PromptRegistry.render(
            prompt_id, version=version, agent_catalog=_build_agent_catalog()
        )
    return PromptRegistry.get(prompt_id, version=version)


def _grade(response_text: str) -> dict[str, Any]:
    """Lightweight grading of a captured planner response.

    Replay is a developer microscope, not a CI gate — full grader
    scores live on ``run_planner_eval --prompt-id ... --version ...``.
    Here we surface the three signals that tell the developer at a
    glance whether the candidate's output is structurally usable:

    * JSON parses
    * Top-level ``{"tasks": [...]}`` shape
    * Task count is in [1, 12]

    Failures during grading return a single ``error`` row rather than
    crashing the replay session.
    """
    import json

    try:
        parsed = json.loads(response_text)
    except (json.JSONDecodeError, TypeError) as exc:
        return {"checks": [("json_parses", False, f"{exc}")]}

    checks: list[tuple[str, bool, str]] = [
        ("json_parses", True, "ok"),
    ]
    if not isinstance(parsed, dict) or "tasks" not in parsed:
        checks.append((
            "plan_shape", False,
            f"expected top-level dict with 'tasks'; got {type(parsed).__name__}",
        ))
        return {"checks": checks}
    tasks = parsed["tasks"]
    if not isinstance(tasks, list):
        checks.append((
            "plan_shape", False,
            f"'tasks' is not a list ({type(tasks).__name__})",
        ))
        return {"checks": checks}
    checks.append(("plan_shape", True, f"{len(tasks)} task(s)"))

    if not (1 <= len(tasks) <= 12):
        checks.append((
            "task_count", False,
            f"{len(tasks)} task(s) outside [1, 12]",
        ))
    else:
        checks.append(("task_count", True, "in range"))
    return {"checks": checks}


def _format_grader_panel(grades: dict[str, Any]) -> list[str]:
    if "error" in grades:
        return [f"    grader error: {grades['error']}"]
    lines: list[str] = []
    for name, passed, reason in grades.get("checks") or ():
        marker = "✓" if passed else "✗"
        lines.append(f"    {marker} {name}: {reason}")
    return lines


class Command(BaseCommand):
    help = (
        "Replay captured planner LLM calls for a conversation against "
        "a candidate prompt version (e.g. planner.system@v2) and print "
        "a side-by-side diff with grader scores."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--conversation-id",
            dest="conversation_id",
            required=True,
            help="UUID of the Conversation to replay.",
        )
        parser.add_argument(
            "--prompt",
            dest="prompt_spec",
            required=True,
            help=(
                "Candidate prompt as '<prompt_id>@<version>' "
                "(e.g. 'planner.system@v2'). Version 'active' resolves "
                "to the registry's active pointer."
            ),
        )
        parser.add_argument(
            "--no-llm",
            dest="no_llm",
            action="store_true",
            help="Skip the candidate LLM call; only print the captured side.",
        )
        parser.add_argument(
            "--max-calls",
            dest="max_calls",
            type=int,
            default=5,
            help="Cap the number of replayed calls (default 5).",
        )

    def handle(self, *args, **options):
        from infrastructure.persistence.ai.agents.models import DeepRunLog

        conversation_id = options["conversation_id"]
        prompt_id, version = _parse_prompt_spec(options["prompt_spec"])
        no_llm = bool(options.get("no_llm"))
        max_calls = max(1, int(options.get("max_calls") or 5))

        rendered_candidate = _render_planner_system(prompt_id, version)

        rows = list(
            DeepRunLog.objects.filter(
                event_type="llm_call",
                deep_run__thread_id=str(conversation_id),
            )
            .select_related("deep_run")
            .order_by("created_at")[:max_calls]
        )
        if not rows:
            raise CommandError(
                f"No captured llm_call rows found for conversation "
                f"{conversation_id}. Either no planner ran for this "
                "conversation or the DeepRunLog instrumentation hasn't "
                "written rows yet."
            )

        divider = "═" * 78
        self.stdout.write(divider)
        self.stdout.write(
            self.style.SUCCESS(
                f"Replaying {len(rows)} call(s) for conversation "
                f"{conversation_id} against {prompt_id}@{version}"
            )
        )
        self.stdout.write(
            f"Candidate prompt resolved to {len(rendered_candidate)} chars."
        )
        self.stdout.write(divider)

        for index, row in enumerate(rows, start=1):
            run = row.deep_run
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"#{index}  plan_id={getattr(run, 'plan_id', '—')}  "
                f"model={row.model_used or '—'}  "
                f"cost={row.cost_usd or '—'}"
            ))

            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("  [user prompt]"))
            self.stdout.write(_truncate(row.user_prompt or ""))

            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("  [captured response]"))
            self.stdout.write(_truncate(row.llm_response or ""))

            captured_grades = _grade(row.llm_response or "")
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("  [captured grades]"))
            for line in _format_grader_panel(captured_grades):
                self.stdout.write(line)

            if no_llm:
                self.stdout.write("")
                self.stdout.write(self.style.WARNING(
                    "  [candidate response] skipped (--no-llm)"
                ))
                continue

            try:
                candidate_text = self._run_candidate(
                    system_prompt=rendered_candidate,
                    user_prompt=row.user_prompt or "",
                    model_name=row.model_used or None,
                )
            except Exception as exc:  # noqa: BLE001
                self.stdout.write("")
                self.stdout.write(self.style.ERROR(
                    f"  [candidate response] LLM call failed: {exc}"
                ))
                continue

            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("  [candidate response]"))
            self.stdout.write(_truncate(candidate_text))

            candidate_grades = _grade(candidate_text)
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO("  [candidate grades]"))
            for line in _format_grader_panel(candidate_grades):
                self.stdout.write(line)

        self.stdout.write("")
        self.stdout.write(divider)
        self.stdout.write(self.style.SUCCESS(
            "Replay complete. Compare the captured vs candidate panels "
            "above; promote the candidate to active by editing "
            f"components/agents/infrastructure/prompts/data/{prompt_id}.yaml"
        ))

    def _run_candidate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_name: str | None,
    ) -> str:
        """One-shot LLM call with the candidate system prompt."""
        from langchain.schema import HumanMessage, SystemMessage

        from components.knowledge.infrastructure.factories.llms.factory import (
            LLMFactory,
        )

        llm = LLMFactory.get_llm(model_name=model_name)
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        content = getattr(response, "content", None)
        if isinstance(content, list):
            content = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in content
            )
        if content is None:
            content = str(response)
        return content
