"""Django adapter for ``EvalExampleStorePort`` (SEE-190).

Persists + reads labeled eval examples via the ``prompt_eval.PromptEvalExample``
model. ``add_example`` is idempotent on the
``(artifact_type, artifact_id, feedback_decision)`` unique triple; a replayed
decision writes nothing new and returns ``None``.
"""

from __future__ import annotations

from components.agents.application.ports.eval_example_store_port import (
    EvalExampleStorePort,
)
from components.agents.domain.value_objects.eval_example import (
    EvalExample,
    ExampleSource,
    FeedbackDecision,
)


class DjangoEvalExampleRepository(EvalExampleStorePort):
    def add_example(self, example: EvalExample) -> str | None:
        from infrastructure.persistence.prompt_eval.models import PromptEvalExample

        obj, created = PromptEvalExample.objects.get_or_create(
            artifact_type=example.artifact_type,
            artifact_id=example.artifact_id,
            feedback_decision=example.feedback_decision.value,
            defaults={
                "dataset_name": example.dataset_name,
                "case_id": example.case_id,
                "category": example.category,
                "goal": example.goal,
                "input_data": example.input_data,
                "expected_output": example.expected_output,
                "source_type": example.source_type.value,
                "feedback_codes": list(example.feedback_codes),
                "feedback_note": example.feedback_note,
                "risk_band": example.risk_band,
                "reviewer_id": example.reviewer_id,
                "workspace_id": example.workspace_id,
            },
        )
        return str(obj.pk) if created else None

    def list_examples(self, dataset_name: str) -> list[EvalExample]:
        from infrastructure.persistence.prompt_eval.models import PromptEvalExample

        rows = PromptEvalExample.objects.filter(dataset_name=dataset_name).order_by(
            "-created_at"
        )
        return [self._to_entity(row) for row in rows]

    def list_recent_negatives(
        self, workspace_id: str, artifact_type: str, limit: int
    ) -> list[EvalExample]:
        from infrastructure.persistence.prompt_eval.models import PromptEvalExample

        # Workspace isolation is mandatory — always filter workspace_id so one
        # workspace never sees another's reviewer feedback.
        if not workspace_id or limit <= 0:
            return []
        rows = PromptEvalExample.objects.filter(
            workspace_id=str(workspace_id),
            artifact_type=artifact_type,
            feedback_decision__in=(
                FeedbackDecision.CHANGES_REQUESTED.value,
                FeedbackDecision.REJECTED.value,
            ),
        ).order_by("-created_at")[:limit]
        return [self._to_entity(row) for row in rows]

    @staticmethod
    def _to_entity(row) -> EvalExample:
        return EvalExample(
            dataset_name=row.dataset_name,
            case_id=row.case_id,
            category=row.category,
            goal=row.goal,
            feedback_decision=FeedbackDecision(row.feedback_decision),
            artifact_type=row.artifact_type,
            artifact_id=row.artifact_id,
            input_data=row.input_data or {},
            expected_output=row.expected_output or {},
            source_type=ExampleSource(row.source_type),
            feedback_codes=list(row.feedback_codes or []),
            feedback_note=row.feedback_note or "",
            risk_band=row.risk_band or "",
            reviewer_id=row.reviewer_id or "",
            workspace_id=row.workspace_id or "",
        )
