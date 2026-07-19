"""Run the planner against an eval dataset and write a baseline report.

Usage:
  python manage.py run_planner_eval --dataset planner_v1
  python manage.py run_planner_eval --dataset planner_v1 --samples 5
  python manage.py run_planner_eval --dataset planner_v1 --grader gpt-4o-mini

The dataset slug resolves against ``components/agents/tests/prompt_eval/datasets/<slug>.json``.
Output: an HTML report and a JSON report under ``docs/eval-reports/``,
both stamped with the dataset name and the run timestamp.

The planner runs without a real ``DeepRun`` row (the eval harness
doesn't create one), so the Wave 1 instrumentation in ``_log_llm_call``
silently skips the row write — no eval traffic clutters the
production log. The cost of a single run is roughly:

  case_count × (1 planner call + 1 grader call) × per-call cost

For a 15-case dataset against gpt-4o-mini both ends, that's about
$0.10 per invocation today. Use ``--samples`` for cheaper sanity
runs while iterating.

Plan reference: ``/Users/henrywanjala/.claude/plans/atomic-gathering-fox.md``
Wave 2.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


# Default workspace placeholder used when a test case does not
# supply a workspace context. The planner just threads this through
# its prompt; the value is only meaningful if a tool tries to use
# it (the eval harness never invokes tools, only the planner).
EVAL_WORKSPACE_ID = "00000000-0000-0000-0000-000000000000"


def _build_run_prompt_function():
    """Closure wrapping the planner so the harness can call it per case."""
    from components.agents.infrastructure.adapters.langchain.deep import (
        llm_planner,
    )

    def run_prompt_function(case: dict[str, Any]):
        goal = str(case.get("goal") or "")
        context = case.get("context") or {}
        # ``plan_with_llm`` accepts an ``extra_context`` dict. The
        # planner's system prompt looks for ``context.conversation_history``
        # and ``context.retrieved_context`` keys; we just pass the
        # case's context through.
        try:
            return llm_planner.plan_with_llm(
                goal=goal,
                plan_id=str(uuid.uuid4()),
                workspace_id=EVAL_WORKSPACE_ID,
                extra_context=context if isinstance(context, dict) else None,
            )
        except Exception as exc:
            # Per the harness contract — return None and let
            # ``grade_plan_shape`` record a 0/10 reason rather than
            # bubbling. Logged so a debugger can still find it.
            logger.warning("Planner failed for case=%s: %s", case.get("id"), exc)
            return None

    return run_prompt_function


class Command(BaseCommand):
    help = "Run the planner against an eval dataset and write a baseline HTML + JSON report under docs/eval-reports/."

    # This command defines its own ``--version`` (the PromptRegistry
    # version to evaluate), which collides with the ``--version`` action
    # Django's BaseCommand parser adds by default. Suppress the base
    # one from help AND resolve the argparse conflict so the command's
    # own flag wins — without this the command raises ArgumentError at
    # parser construction and is not invocable at all.
    suppressed_base_arguments = {"--version"}

    def create_parser(self, prog_name, subcommand, **kwargs):
        kwargs.setdefault("conflict_handler", "resolve")
        return super().create_parser(prog_name, subcommand, **kwargs)

    def add_arguments(self, parser):
        parser.add_argument(
            "--dataset",
            type=str,
            default="planner_v1",
            help=(
                "Dataset slug — resolves to "
                "components/agents/tests/prompt_eval/datasets/<slug>.json. "
                "Default: planner_v1."
            ),
        )
        parser.add_argument(
            "--dataset-path",
            dest="dataset_path",
            type=str,
            default="",
            help=(
                "Absolute or relative path to a dataset JSON, overriding "
                "--dataset. Useful for ad-hoc runs against a subset of "
                "cases without committing a new dataset file."
            ),
        )
        parser.add_argument(
            "--samples",
            type=int,
            default=0,
            help=("If > 0, evaluate only the first N cases. Useful for cheap sanity runs while iterating on a prompt."),
        )
        parser.add_argument(
            "--grader",
            type=str,
            default="gpt-4o-mini",
            help="Grader model name (LLMFactory slug). Default: gpt-4o-mini.",
        )
        parser.add_argument(
            "--judge-provider",
            dest="judge_provider",
            type=str,
            default=None,
            choices=["openai", "azure", "anthropic"],
            help=(
                "LLMFactory provider for the judge. Defaults to auto-detect "
                "(Azure if env present, else OpenAI). Pass 'anthropic' to "
                "cross-check Claude vs GPT on the same dataset — the "
                "Logseq curriculum's single most effective debiasing move."
            ),
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=3,
            help="Max concurrent eval cases. Default: 3 (rate-limit safe).",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="docs/eval-reports",
            help="Where to write the HTML + JSON reports.",
        )
        parser.add_argument(
            "--label",
            type=str,
            default="baseline",
            help=(
                "Free-form label embedded in the output filename — useful when comparing pre- vs post-prompt-edit runs."
            ),
        )
        parser.add_argument(
            "--prompt-id",
            dest="prompt_id",
            type=str,
            default="planner.system",
            help=(
                "Prompt id from PromptRegistry to evaluate. Default: "
                "planner.system. Only ``planner.system`` is meaningful "
                "today — the other registered prompts aren't planner-level."
            ),
        )
        parser.add_argument(
            "--version",
            type=str,
            default="active",
            help=(
                "Prompt version. Default: 'active' (resolves the YAML's "
                "active pointer). Pass an explicit version (e.g. 'v1') to "
                "compare a candidate against the live prompt without "
                "flipping the active pointer."
            ),
        )

    def handle(self, *args, **options):
        from components.agents.infrastructure.evaluation.prompt_evaluator import (
            PromptEvaluator,
        )
        from components.agents.tests.prompt_eval.graders.code import (
            grade_with_code,
        )
        from components.agents.tests.prompt_eval.graders.model.planner_judge import (
            PlannerJudge,
        )

        dataset_slug = options["dataset"]
        dataset_override = options.get("dataset_path") or ""
        samples = int(options["samples"] or 0)
        grader_model = options["grader"]
        judge_provider = options.get("judge_provider")
        concurrency = max(1, int(options["concurrency"]))
        output_dir = Path(options["output_dir"])
        label = options["label"]
        prompt_id = options["prompt_id"]
        version = options["version"]

        # Swap the planner's system prompt template to the requested
        # version BEFORE the harness wires up its closure. The planner
        # re-reads SYSTEM_PROMPT_TEMPLATE on every call, so this picks
        # up the new version for every case in the run.
        self._pin_planner_prompt(prompt_id, version)

        if dataset_override:
            dataset_path = Path(dataset_override).expanduser().resolve()
            dataset_slug = dataset_path.stem
            if not dataset_path.exists():
                raise CommandError(f"Dataset not found at override path: {dataset_path}")
        else:
            # __file__ is at components/agents/cli/management/commands/<file>.
            # parents[3] is components/agents/, where the tests/ tree lives.
            dataset_path = (
                Path(__file__).resolve().parents[3] / "tests" / "prompt_eval" / "datasets" / f"{dataset_slug}.json"
            )
            if not dataset_path.exists():
                raise CommandError(
                    f"Dataset not found: {dataset_path}. Looked under components/agents/tests/prompt_eval/datasets/."
                )

        if samples > 0:
            dataset_path = self._truncate_dataset(dataset_path, samples)

        evaluator = PromptEvaluator(
            code_grader=grade_with_code,
            model_grader=PlannerJudge(
                model_name=grader_model,
                provider=judge_provider,
            ),
            max_concurrent_tasks=concurrency,
            grader_label=grader_model,
        )
        run_prompt_function = _build_run_prompt_function()

        self.stdout.write(
            self.style.SUCCESS(
                f"Running planner eval — dataset={dataset_slug} "
                f"grader={grader_model} concurrency={concurrency}" + (f" samples={samples}" if samples else "")
            )
        )

        report = evaluator.run_evaluation(
            run_prompt_function=run_prompt_function,
            dataset_path=dataset_path,
            dataset_name=dataset_slug,
        )

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        # Per-version reports keep v1 / v2 runs from overwriting each
        # other when both are kicked off in the same minute.
        version_suffix = f"-{prompt_id.replace('.', '_')}-{version}"
        # Cross-vendor judge runs (--judge-provider anthropic) carry the
        # provider in the filename so OpenAI vs Claude runs against the
        # same prompt+version don't overwrite each other.
        judge_suffix = f"-judge_{judge_provider}" if judge_provider else ""
        stem = f"planner-{label}{version_suffix}{judge_suffix}-{timestamp}"
        html_path = evaluator.write_html_report(
            report,
            output_path=output_dir / f"{stem}.html",
        )
        json_path = evaluator.write_json_report(
            report,
            output_path=output_dir / f"{stem}.json",
        )

        # Inject the eval-run metadata into the JSON so the V2 panel +
        # PromptEvalReportsViewSet can render prompt_id / version /
        # label / judge_provider without re-parsing the filename. The
        # EvaluationReport dataclass doesn't carry these fields (they're
        # CLI knobs, not part of the eval surface).
        import json as _json

        try:
            report_data = _json.loads(json_path.read_text())
        except (OSError, _json.JSONDecodeError):
            report_data = {}
        report_data["_meta"] = {
            "prompt_id": prompt_id,
            "version": version,
            "label": label,
            "judge_provider": judge_provider or "auto",
            "created_at": timestamp,
            "html_filename": f"{stem}.html",
        }
        json_path.write_text(_json.dumps(report_data, indent=2, default=str))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Eval summary"))
        self.stdout.write(f"  cases:        {report.case_count}")
        self.stdout.write(f"  avg score:    {report.average_score:.2f} / 10")
        self.stdout.write(f"  pass rate:    {report.pass_rate_at_seven * 100:.0f}% (≥7/10)")
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Score by category"))
        for cat, score in sorted(report.score_by_category.items()):
            self.stdout.write(f"  {cat:<20s} {score:.2f}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"  HTML: {html_path}"))
        self.stdout.write(self.style.SUCCESS(f"  JSON: {json_path}"))

    def _pin_planner_prompt(self, prompt_id: str, version: str) -> None:
        """Swap ``SYSTEM_PROMPT_TEMPLATE`` to the requested registry version.

        Only ``planner.system`` is meaningful today — the other registered
        prompts aren't used at the planner-level call site. Calling this
        with a different prompt_id raises so the developer doesn't
        silently run the live prompt thinking they pinned a different one.
        """
        if prompt_id != "planner.system":
            raise CommandError(
                f"--prompt-id={prompt_id!r} not supported yet; only "
                "'planner.system' is wired into run_planner_eval. Other "
                "prompts (estimator.*) need their own eval dataset + "
                "harness — see the atomic-gathering-fox plan."
            )
        from components.agents.infrastructure.adapters.langchain.deep import (
            llm_planner,
        )
        from components.agents.infrastructure.prompts.registry import (
            PromptRegistry,
        )

        resolved = PromptRegistry.active_version(prompt_id) if version == "active" else version
        llm_planner.SYSTEM_PROMPT_TEMPLATE = PromptRegistry.get(prompt_id, version=resolved)
        self.stdout.write(self.style.SUCCESS(f"Pinned {prompt_id}@{resolved} as the planner prompt for this eval run."))

    @staticmethod
    def _truncate_dataset(source: Path, samples: int) -> Path:
        """Materialise a temporary truncated dataset and return its path."""
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
