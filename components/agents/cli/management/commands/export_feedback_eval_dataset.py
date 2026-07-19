"""Export the accumulated sign-off feedback examples as an eval dataset (SEE-190).

Reads every ``PromptEvalExample`` on the ``feedback-<artifact_type>`` dataset
(via the repository, not the ORM directly) and writes a JSON file in the
``PromptEvaluator`` "cases" format — ``{"cases": [...]}`` — so the writing /
newsletter quality rubric (SEE-173) can run against real reviewer feedback.

Usage::

    python manage.py export_feedback_eval_dataset --artifact-type newsletter \\
        --out docs/eval-reports/feedback-newsletter.json
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Export accumulated sign-off feedback eval examples for an artifact "
        "type as a PromptEvaluator 'cases' JSON dataset."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--artifact-type",
            dest="artifact_type",
            required=True,
            help="Artifact type to export, e.g. 'newsletter' or 'writing_draft'.",
        )
        parser.add_argument(
            "--out",
            dest="out",
            required=True,
            help="Output JSON path.",
        )

    def handle(self, *args, **options):
        from components.agents.infrastructure.repositories.django_eval_example_repository import (
            DjangoEvalExampleRepository,
        )

        artifact_type = options["artifact_type"]
        out_path = Path(options["out"]).expanduser()
        dataset_name = f"feedback-{artifact_type}"

        examples = DjangoEvalExampleRepository().list_examples(dataset_name)
        cases = [self._to_case(example) for example in examples]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"cases": cases}, indent=2, default=str),
            encoding="utf-8",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Exported {len(cases)} case(s) from '{dataset_name}' to {out_path}"
            )
        )

    @staticmethod
    def _to_case(example) -> dict:
        return {
            "id": example.case_id,
            "category": example.category,
            "goal": example.goal,
            "input_data": example.input_data,
            "expected_output": example.expected_output,
            "feedback_decision": example.feedback_decision.value,
            "feedback_codes": list(example.feedback_codes),
            "feedback_note": example.feedback_note,
            "risk_band": example.risk_band,
        }
