"""Composition root for EVALUATE (architecture-manifesto Rule 9).

Providers decide which adapter implements which port. That is a POLICY
decision, so it lives in the application layer — and it is what lets the
controller stay free of concrete infrastructure, which
`test_cross_context_import_rules` and `test_controller_orm_import_rules` both
enforce.

Imports are function-local on purpose: this module is imported from the API
layer, and dragging Django ORM modules in at import time is what those tests
exist to prevent.
"""

from __future__ import annotations


class EvaluationProvider:
    def repository(self):
        from components.evaluation.infrastructure.repositories.eval_repository import (
            DjangoEvalRepository,
        )

        return DjangoEvalRepository()

    def price_lookup(self):
        from components.evaluation.infrastructure.adapters.catalogue_price_lookup import (
            catalogue_price_lookup,
        )

        return catalogue_price_lookup

    def availability_reader(self):
        from components.evaluation.infrastructure.adapters.finding_case_miner import (
            workspace_availability,
        )

        return workspace_availability

    def create_progress_job(self, *, workspace_id, run_id, title):
        """A BackgroundJob for the HUD's existing progress surface.

        Returns ``None`` when the job cannot be created. Progress is a nicety;
        the run is the product, and losing the job row must not lose the run.
        """
        try:
            from infrastructure.persistence.core.models import BackgroundJob

            return BackgroundJob.objects.create(
                workspace_id=workspace_id,
                job_type="evaluation_run",
                resource_id=str(run_id)[:64],
                title=title,
            )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "eval_background_job_create_failed run=%s", run_id
            )
            return None

    def enqueue_run(self, run_id: str) -> None:
        from components.evaluation.infrastructure.tasks.eval_run_tasks import run_eval_suite

        run_eval_suite.delay(str(run_id))

    def workspace_ai_config(self, workspace_id) -> dict:
        try:
            from components.workspace.application.providers.workspaces_models_provider import (
                get_workspaces_models_provider,
            )

            Workspace = get_workspaces_models_provider().Workspace
            row = Workspace.objects.filter(id=workspace_id).values("ai_config").first()
            return (row or {}).get("ai_config") or {}
        except Exception:
            return {}


_default = EvaluationProvider()


def get_evaluation_provider() -> EvaluationProvider:
    return _default
