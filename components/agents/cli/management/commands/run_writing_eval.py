"""Run the writing generator against an eval dataset and write a report (SEE-173).

Usage:
  python manage.py run_writing_eval --dataset writing_v1
  python manage.py run_writing_eval --dataset writing_v1 --samples 1
  python manage.py run_writing_eval --dataset writing_v1 --grader gpt-4o-mini --gen-model gpt-4o-mini

For each case the harness GENERATES a draft via the same
``GenerateInteractiveDraftUseCase`` the editor "Ask AI" path uses — but
grounded in the case fixture's facts (a stub retrieval port) so the run is
deterministic and offline-friendly, and steered by the case's voice rules.
It then scores the draft with deterministic code graders (faithfulness,
voice, readability, structure) + an LLM rubric judge (warmth, specificity,
clarity/CTA, on-voice), and writes HTML + JSON reports under
``docs/eval-reports/`` (surfaced by the existing PromptEvalReportsViewSet).

Establishing a baseline: run once, record the scores (sred:result). To
detect a regression, change the writing prompt/model and re-run — the
score delta is the signal.

Cost ≈ case_count × (1 generation call + 1 judge call). Use ``--samples``
for cheap iteration. Both calls hit a real LLM, so this is an operator
command, not a CI test.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

# Placeholder workspace — the eval grounds in the case fixture's facts via
# the stub retrieval port, so no real workspace data is read.
EVAL_WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"


class _FixtureRetrieval:
    """Stub WorkspaceRetrievalPort — returns the case's fixture facts.

    Grounding the generation in the same facts the graders check against
    makes the run deterministic and decouples it from live workspace data.
    """

    def __init__(self, facts: list[str]) -> None:
        self._facts = list(facts or [])

    def search(self, *args: Any, **kwargs: Any) -> list[Any]:  # noqa: ARG002
        return [
            SimpleNamespace(content=fact, metadata={}, score=1.0)
            for fact in self._facts
        ]


class _FixtureVoice:
    """Stub voice-profile reader — returns a fixed style card string."""

    def __init__(self, card: str) -> None:
        self._card = card

    def style_card(self, *args: Any, **kwargs: Any) -> str:  # noqa: ARG002
        return self._card


def _voice_card(voice: dict[str, Any]) -> str:
    """Render the case's voice rules into a prompt style-card (style only)."""
    if not voice:
        return ""
    parts: list[str] = []
    tone = str(voice.get("tone") or "").strip()
    if tone:
        parts.append(f"Tone: {tone}.")
    preferred = str(voice.get("preferred") or "").strip()
    banned = [str(t).strip() for t in (voice.get("banned_terms") or []) if str(t).strip()]
    if preferred and banned:
        parts.append(
            f"Always refer to the people served as '{preferred}'; "
            f"never use the words {', '.join(banned)}."
        )
    elif banned:
        parts.append(f"Never use the words {', '.join(banned)}.")
    if not parts:
        return ""
    return "VOICE & STYLE (how the copy should read — not facts):\n" + " ".join(parts)


def _build_run_prompt_function(gen_model: str):
    from components.agents.application.use_cases.generate_interactive_draft_use_case import (
        GenerateInteractiveDraftUseCase,
    )
    from components.knowledge.application.providers.ai_llm_provider import (
        AILlmProvider,
    )

    def run_prompt_function(case: dict[str, Any]):
        context = dict(case.get("context") or {})
        kind = str(context.get("kind") or "letter")
        facts = context.get("retrieved_context") or []
        voice_card = _voice_card(context.get("voice") or {})

        # The document context the use case reads (title/recipient/period/
        # entity/prompt) — strip the eval-only keys.
        exec_ctx = {
            k: v
            for k, v in context.items()
            if k not in ("retrieved_context", "voice", "kind")
        }

        use_case = GenerateInteractiveDraftUseCase(
            retrieval_port=_FixtureRetrieval(facts),
            llm_port=AILlmProvider().get_default_port(
                model_name=gen_model, temperature=0.4
            ),
            fact_sheet_port=None,
            voice_profile_port=_FixtureVoice(voice_card) if voice_card else None,
        )
        try:
            return use_case.execute(
                workspace_id=EVAL_WORKSPACE_ID, kind=kind, context=exec_ctx
            )
        except Exception as exc:  # noqa: BLE001
            # Per the harness contract — return None so the code graders
            # record a 0 rather than bubbling.
            logger.warning("Writing generation failed for case=%s: %s", case.get("id"), exc)
            return None

    return run_prompt_function


class Command(BaseCommand):
    help = (
        "Run the writing generator against an eval dataset and write a "
        "writing-quality HTML + JSON report under docs/eval-reports/."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dataset", type=str, default="writing_v1")
        parser.add_argument("--dataset-path", dest="dataset_path", type=str, default="")
        parser.add_argument("--samples", type=int, default=0)
        parser.add_argument(
            "--grader", type=str, default="gpt-4o-mini",
            help="Judge model (LLMFactory slug). Default: gpt-4o-mini.",
        )
        parser.add_argument(
            "--gen-model", dest="gen_model", type=str, default="gpt-3.5-turbo",
            help="Generation model — matches the prod draft path default.",
        )
        parser.add_argument(
            "--judge-provider", dest="judge_provider", type=str, default=None,
            choices=["openai", "azure", "anthropic"],
        )
        parser.add_argument("--concurrency", type=int, default=3)
        parser.add_argument("--output-dir", type=str, default="docs/eval-reports")
        parser.add_argument("--label", type=str, default="baseline")
        parser.add_argument(
            "--prompt-id", dest="prompt_id", type=str, default="writing.system",
            help="Family id recorded in the report for the browser. Default: writing.system.",
        )

    def handle(self, *args, **options):
        from components.agents.infrastructure.evaluation.prompt_evaluator import (
            PromptEvaluator,
        )
        from components.agents.tests.prompt_eval.graders.writing import (
            WritingJudge,
            grade_writing_with_code,
        )

        dataset_slug = options["dataset"]
        dataset_override = options.get("dataset_path") or ""
        samples = int(options["samples"] or 0)
        grader_model = options["grader"]
        gen_model = options["gen_model"]
        judge_provider = options.get("judge_provider")
        concurrency = max(1, int(options["concurrency"]))
        output_dir = Path(options["output_dir"])
        label = options["label"]
        prompt_id = options["prompt_id"]

        if dataset_override:
            dataset_path = Path(dataset_override).expanduser().resolve()
            dataset_slug = dataset_path.stem
            if not dataset_path.exists():
                raise CommandError(f"Dataset not found at override path: {dataset_path}")
        else:
            dataset_path = (
                Path(__file__).resolve().parents[3]
                / "tests" / "prompt_eval" / "datasets" / f"{dataset_slug}.json"
            )
            if not dataset_path.exists():
                raise CommandError(
                    f"Dataset not found: {dataset_path}. Looked under "
                    "components/agents/tests/prompt_eval/datasets/."
                )

        if samples > 0:
            dataset_path = self._truncate_dataset(dataset_path, samples)

        evaluator = PromptEvaluator(
            code_grader=grade_writing_with_code,
            model_grader=WritingJudge(model_name=grader_model, provider=judge_provider),
            max_concurrent_tasks=concurrency,
            grader_label=grader_model,
        )
        run_prompt_function = _build_run_prompt_function(gen_model)

        self.stdout.write(
            self.style.SUCCESS(
                f"Running writing eval — dataset={dataset_slug} "
                f"gen={gen_model} grader={grader_model} concurrency={concurrency}"
                + (f" samples={samples}" if samples else "")
            )
        )

        report = evaluator.run_evaluation(
            run_prompt_function=run_prompt_function,
            dataset_path=dataset_path,
            dataset_name=dataset_slug,
        )

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        judge_suffix = f"-judge_{judge_provider}" if judge_provider else ""
        stem = f"writing-{label}-{prompt_id.replace('.', '_')}{judge_suffix}-{timestamp}"
        html_path = evaluator.write_html_report(report, output_path=output_dir / f"{stem}.html")
        json_path = evaluator.write_json_report(report, output_path=output_dir / f"{stem}.json")

        import json as _json
        try:
            report_data = _json.loads(json_path.read_text())
        except (OSError, _json.JSONDecodeError):
            report_data = {}
        report_data["_meta"] = {
            "prompt_id": prompt_id,
            "version": "active",
            "label": label,
            "gen_model": gen_model,
            "judge_provider": judge_provider or "auto",
            "created_at": timestamp,
            "html_filename": f"{stem}.html",
        }
        json_path.write_text(_json.dumps(report_data, indent=2, default=str))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Writing eval summary"))
        self.stdout.write(f"  cases:        {report.case_count}")
        self.stdout.write(f"  avg score:    {report.average_score:.2f} / 10")
        self.stdout.write(f"  pass rate:    {report.pass_rate_at_seven * 100:.0f}% (≥7/10)")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Score by kind"))
        for cat, score in sorted(report.score_by_category.items()):
            self.stdout.write(f"  {cat:<20s} {score:.2f}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"  HTML: {html_path}"))
        self.stdout.write(self.style.SUCCESS(f"  JSON: {json_path}"))

    @staticmethod
    def _truncate_dataset(source: Path, samples: int) -> Path:
        import json
        import tempfile

        with source.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        cases = list(data.get("cases") or [])[:samples]
        data["cases"] = cases
        if "_meta" in data:
            data["_meta"]["case_count"] = len(cases)
            data["_meta"]["truncated_to"] = samples
        tmp = Path(tempfile.gettempdir()) / f"{source.stem}-truncated-{samples}.json"
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return tmp
