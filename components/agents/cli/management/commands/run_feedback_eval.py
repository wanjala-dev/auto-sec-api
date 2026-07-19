"""Grade snapshotted reviewer-feedback content against the writing rubric (SEE-191).

Phase 6d — "close the feedback loop", the eval half. Phase 6c turned every human
sign-off decision into a labeled ``PromptEvalExample``; the negative examples
(CHANGES_REQUESTED / REJECTED) carry the exact generated copy the reviewer
flagged, stored on ``expected_output.generated_content``. This command runs the
SEE-173 writing-quality rubric (deterministic code graders + the ``WritingJudge``
LLM-as-judge) against that snapshotted copy and writes HTML + JSON reports under
``docs/eval-reports/`` — auto-surfaced by ``PromptEvalReportsViewSet``.

Eval MODE is **grade the snapshot, do NOT regenerate.** We are not asking the
generator to re-draft; we are scoring the *actual content a human rejected*, so
the rubric numbers become a longitudinal, reviewer-grounded quality signal.

For each configured artifact type it:

1. Exports the feedback dataset by REUSING ``export_feedback_eval_dataset``
   (``call_command``) into a temp file.
2. Normalises each exported case into the shape the writing graders read — a
   ``context`` (grounding facts + kind) plus the pass-through draft built from
   ``expected_output.generated_content``. Cases with no captured content are
   skipped (a metadata-only positive override has nothing to grade).
3. Runs ``PromptEvaluator`` with ``grade_writing_with_code`` + ``WritingJudge``.
4. Writes JSON + HTML with a ``_meta`` block (``source="sign_off_feedback"``) so
   the report browser lists it alongside the SEE-173 baseline runs.

Per-artifact-type failures are isolated — one type blowing up (e.g. a flaky
judge) does not abort the others. The scheduled Celery task
(``agents.run_reviewer_feedback_eval``) simply invokes this command weekly.

The judge hits a real LLM, so this is an operator/scheduled command, not a CI
test. Cost ≈ case_count × 1 judge call.

NOTE on the default artifact-type list: Phase 6c tags every writing draft
(letter / summary / blog / update / …) under the single artifact type
``writing_draft`` and newsletters under ``newsletter`` — those are the ONLY two
``feedback-*`` datasets that actually accumulate rows. The default is therefore
``newsletter, writing_draft`` (not a per-kind list) so no captured feedback is
silently left un-evaluated. Pass ``--artifact-type`` to narrow it.
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

# The artifact types Phase 6c actually writes feedback datasets for.
DEFAULT_ARTIFACT_TYPES = ("newsletter", "writing_draft")

# Artifact type -> the ``kind`` the writing graders key on (only "newsletter"
# triggers the sections structural check; everything else is a plain document).
_KIND_BY_ARTIFACT_TYPE = {
    "newsletter": "newsletter",
}


def _build_pass_through_run_prompt_function(artifact_type: str):
    """Return a run_prompt_function that REPLAYS the snapshotted content.

    The harness contract is ``run_prompt_function(case) -> plan | None``. Here
    the "plan" is the writing draft dict the graders expect
    (``{title, body_html, sections, ...}``) rebuilt from the case's
    ``expected_output.generated_content``. Cases with no captured content return
    ``None`` (the harness records a 0 / skip rather than bubbling).
    """

    def run_prompt_function(case: dict[str, Any]):
        expected = case.get("expected_output") or {}
        generated = expected.get("generated_content")
        if not generated:
            return None
        body_html = generated if isinstance(generated, str) else str(generated)
        # The capture snapshots body_html only (no title/sections), so we do NOT
        # fabricate those — an honest empty title/sections is a true statement
        # about what the reviewer actually saw and flagged.
        return {
            "title": "",
            "body_html": body_html,
            "excerpt": "",
            "sections": [],
        }

    return run_prompt_function


def _normalise_case(case: dict[str, Any], kind: str) -> dict[str, Any]:
    """Add the ``context`` the writing graders read to an exported feedback case.

    The exported case carries grounding facts on ``input_data.grounding_texts``;
    the graders read grounding + voice + kind off ``case["context"]``. Voice
    rules aren't captured at sign-off time, so ``voice`` is empty (the voice
    grader then neutrally passes).
    """
    input_data = case.get("input_data") or {}
    enriched = dict(case)
    enriched["context"] = {
        "retrieved_context": list(input_data.get("grounding_texts") or []),
        "voice": {},
        "kind": kind,
    }
    return enriched


class Command(BaseCommand):
    help = (
        "Grade snapshotted reviewer-feedback content against the writing "
        "rubric and write HTML + JSON reports under docs/eval-reports/."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--artifact-type",
            dest="artifact_types",
            action="append",
            default=None,
            help=(
                "Artifact type to evaluate (repeatable). Defaults to "
                f"{', '.join(DEFAULT_ARTIFACT_TYPES)}."
            ),
        )
        parser.add_argument(
            "--grader",
            type=str,
            default="gpt-4o-mini",
            help="Judge model (LLMFactory slug). Default: gpt-4o-mini.",
        )
        parser.add_argument(
            "--judge-provider",
            dest="judge_provider",
            type=str,
            default=None,
            choices=["openai", "azure", "anthropic"],
        )
        parser.add_argument("--concurrency", type=int, default=3)
        parser.add_argument("--output-dir", type=str, default="docs/eval-reports")

    def handle(self, *args, **options):
        artifact_types = options.get("artifact_types") or list(DEFAULT_ARTIFACT_TYPES)
        grader_model = options["grader"]
        judge_provider = options.get("judge_provider")
        concurrency = max(1, int(options["concurrency"]))
        output_dir = Path(options["output_dir"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Running reviewer-feedback eval — types={', '.join(artifact_types)} "
                f"grader={grader_model} concurrency={concurrency}"
            )
        )

        evaluated = 0
        for artifact_type in artifact_types:
            try:
                report = self._eval_one(
                    artifact_type=artifact_type,
                    grader_model=grader_model,
                    judge_provider=judge_provider,
                    concurrency=concurrency,
                    output_dir=output_dir,
                )
            except Exception:  # noqa: BLE001 — isolate per-type failure
                logger.exception(
                    "run_feedback_eval failed artifact_type=%s", artifact_type
                )
                self.stdout.write(
                    self.style.ERROR(f"  {artifact_type}: FAILED (see logs)")
                )
                continue
            if report is not None:
                evaluated += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Reviewer-feedback eval done — {evaluated} report(s) written to {output_dir}"
            )
        )

    def _eval_one(
        self,
        *,
        artifact_type: str,
        grader_model: str,
        judge_provider: str | None,
        concurrency: int,
        output_dir: Path,
    ):
        from components.agents.infrastructure.evaluation.prompt_evaluator import (
            PromptEvaluator,
        )
        from components.agents.tests.prompt_eval.graders.writing import (
            WritingJudge,
            grade_writing_with_code,
        )

        kind = _KIND_BY_ARTIFACT_TYPE.get(artifact_type, artifact_type)
        dataset_name = f"feedback-{artifact_type}"

        # 1. Export the feedback dataset by reusing the SEE-190 export command.
        tmp_dir = Path(tempfile.gettempdir())
        export_path = tmp_dir / f"{dataset_name}-export.json"
        call_command(
            "export_feedback_eval_dataset",
            artifact_type=artifact_type,
            out=str(export_path),
        )

        try:
            exported = json.loads(export_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "run_feedback_eval export unreadable artifact_type=%s err=%s",
                artifact_type,
                exc,
            )
            return None

        raw_cases = list(exported.get("cases") or [])
        if not raw_cases:
            logger.info(
                "run_feedback_eval skip artifact_type=%s reason=no_feedback_examples",
                artifact_type,
            )
            self.stdout.write(f"  {artifact_type}: skipped (no feedback examples)")
            return None

        # 2. Keep only cases that carry gradeable content, enrich with context.
        cases = [
            _normalise_case(case, kind)
            for case in raw_cases
            if (case.get("expected_output") or {}).get("generated_content")
        ]
        if not cases:
            logger.info(
                "run_feedback_eval skip artifact_type=%s reason=no_snapshotted_content",
                artifact_type,
            )
            self.stdout.write(
                f"  {artifact_type}: skipped (no snapshotted content to grade)"
            )
            return None

        dataset_path = tmp_dir / f"{dataset_name}-eval.json"
        dataset_path.write_text(
            json.dumps({"cases": cases}, default=str), encoding="utf-8"
        )

        # 3. Run the writing rubric against the replayed content.
        evaluator = PromptEvaluator(
            code_grader=grade_writing_with_code,
            model_grader=WritingJudge(model_name=grader_model, provider=judge_provider),
            max_concurrent_tasks=concurrency,
            grader_label=grader_model,
        )
        report = evaluator.run_evaluation(
            run_prompt_function=_build_pass_through_run_prompt_function(artifact_type),
            dataset_path=dataset_path,
            dataset_name=dataset_name,
        )

        # 4. Write reports + a _meta block the report browser reads.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        prompt_id = f"writing.{artifact_type}"
        stem = f"feedback-{artifact_type}-{prompt_id.replace('.', '_')}-{timestamp}"
        html_path = evaluator.write_html_report(
            report, output_path=output_dir / f"{stem}.html"
        )
        json_path = evaluator.write_json_report(
            report, output_path=output_dir / f"{stem}.json"
        )

        try:
            report_data = json.loads(json_path.read_text())
        except (OSError, json.JSONDecodeError):
            report_data = {}
        report_data["_meta"] = {
            "prompt_id": prompt_id,
            "version": "active",
            "label": "sign_off_feedback",
            "source": "sign_off_feedback",
            "artifact_type": artifact_type,
            "judge_provider": judge_provider or "auto",
            "created_at": timestamp,
            "html_filename": f"{stem}.html",
        }
        json_path.write_text(json.dumps(report_data, indent=2, default=str))

        self.stdout.write(
            self.style.SUCCESS(
                f"  {artifact_type}: {report.case_count} case(s), "
                f"avg {report.average_score:.2f}/10, "
                f"pass {report.pass_rate_at_seven * 100:.0f}% → {json_path.name}"
            )
        )
        logger.info(
            "run_feedback_eval done artifact_type=%s cases=%s avg=%.2f",
            artifact_type,
            report.case_count,
            report.average_score,
        )
        return report
