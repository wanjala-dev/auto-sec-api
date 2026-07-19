"""Port for persisting + reading labeled eval examples.

Phase 6c (SEE-190). The record-feedback use case depends on this ABC, not on
the Django ORM; the concrete adapter lives in
``components/agents/infrastructure/repositories/django_eval_example_repository.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from components.agents.domain.value_objects.eval_example import EvalExample


class EvalExampleStorePort(ABC):
    @abstractmethod
    def add_example(self, example: EvalExample) -> str | None:
        """Persist an eval example, idempotently.

        Returns the stored row's id, or ``None`` when an example for the
        same ``(artifact_type, artifact_id, feedback_decision)`` triple
        already exists (an idempotent replay — nothing new was written).
        """

    @abstractmethod
    def list_examples(self, dataset_name: str) -> list[EvalExample]:
        """Return every stored example on ``dataset_name``."""

    @abstractmethod
    def list_recent_negatives(
        self, workspace_id: str, artifact_type: str, limit: int
    ) -> list[EvalExample]:
        """Return recent NEGATIVE examples for a workspace + artifact type.

        Negatives are the ``CHANGES_REQUESTED`` / ``REJECTED`` decisions — the
        reviewer counter-examples the few-shot injection (SEE-191) surfaces so a
        generator can avoid repeating flagged mistakes. Ordered newest-first and
        capped at ``limit``. **Workspace-scoped by contract** — an adapter MUST
        filter on ``workspace_id`` so one workspace never sees another's
        feedback.
        """
