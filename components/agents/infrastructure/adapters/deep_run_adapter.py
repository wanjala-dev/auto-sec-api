"""Infrastructure adapter wrapping the deep-run service functions behind DeepRunPort."""

from __future__ import annotations

from typing import Any

from components.agents.application.ports.deep_run_port import DeepRunPort


class DeepRunAdapter(DeepRunPort):
    """Delegates to ``apps.ai.agents.deep`` orchestration functions."""

    def run_plan(
        self,
        *,
        plan: Any,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        agent_config: dict,
        thread_id: str,
        sync_to_kanban: bool = True,
    ) -> dict:
        from components.agents.infrastructure.services.deep_service import run_plan_with_agent

        return run_plan_with_agent(
            plan=plan,
            agent_type=agent_type,
            user_id=user_id,
            workspace_id=workspace_id,
            agent_config=agent_config,
            thread_id=thread_id,
            sync_to_kanban=sync_to_kanban,
        )

    def plan_and_run(
        self,
        *,
        goal: str,
        plan_id: str,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        team_id: str | None = None,
        agent_config: dict,
        model_name: str | None = None,
        sync_to_kanban: bool = True,
        extra_context: dict | None = None,
        deep_pack: str | None = None,
    ) -> dict:
        from components.agents.infrastructure.services.deep_service import plan_and_run_with_llm

        return plan_and_run_with_llm(
            goal=goal,
            plan_id=plan_id,
            agent_type=agent_type,
            user_id=user_id,
            workspace_id=workspace_id,
            team_id=team_id,
            agent_config=agent_config,
            model_name=model_name,
            sync_to_kanban=sync_to_kanban,
            extra_context=extra_context,
            deep_pack=deep_pack,
        )

    # ── Async enqueue (the HTTP path must never block on a deep run) ──────

    @staticmethod
    def _create_pending_run(*, thread_id: str, plan_id: str, user_id: str, workspace_id: str) -> None:
        """Persist the pending DeepRun row the run will transition through.

        ``get_or_create`` (not ``update_or_create``): a client retry with the
        same plan_id must never clobber a run that is already running or
        terminal — the worker-side idempotency guard dedupes the enqueue.
        The runner's own ``update_or_create`` on the same ``thread_id`` then
        flips this row to RUNNING/COMPLETED/FAILED, so the status lifecycle
        is unchanged from the synchronous path.
        """
        from infrastructure.persistence.ai.agents.models import DeepRun

        DeepRun.objects.get_or_create(
            thread_id=thread_id,
            defaults={
                "plan_id": plan_id,
                "user_id": user_id,
                "workspace_id": workspace_id,
                "status": DeepRun.STATUS_PENDING,
            },
        )

    def enqueue_run_plan(
        self,
        *,
        raw_plan: dict,
        plan_id: str,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        team_id: str | None = None,
        agent_config: dict,
        thread_id: str,
        sync_to_kanban: bool = True,
    ) -> None:
        from django.db import transaction

        from components.agents.infrastructure.tasks.agent_tasks import run_deep_run_plan

        self._create_pending_run(thread_id=thread_id, plan_id=plan_id, user_id=user_id, workspace_id=workspace_id)
        # Dispatch after commit (celery-tasks §0) so the worker can never see
        # the task before the pending row exists. IDs/primitives only.
        transaction.on_commit(
            lambda: run_deep_run_plan.delay(
                raw_plan=raw_plan,
                agent_type=agent_type,
                user_id=user_id,
                workspace_id=workspace_id,
                team_id=team_id,
                agent_config=agent_config,
                thread_id=thread_id,
                sync_to_kanban=sync_to_kanban,
            )
        )

    def enqueue_plan_and_run(
        self,
        *,
        goal: str,
        plan_id: str,
        agent_type: str,
        user_id: str,
        workspace_id: str,
        team_id: str | None = None,
        agent_config: dict,
        model_name: str | None = None,
        sync_to_kanban: bool = True,
        extra_context: dict | None = None,
        deep_pack: str | None = None,
    ) -> None:
        from django.db import transaction

        from components.agents.infrastructure.tasks.agent_tasks import run_deep_plan_and_run

        self._create_pending_run(thread_id=plan_id, plan_id=plan_id, user_id=user_id, workspace_id=workspace_id)
        # Dispatch after commit (celery-tasks §0) so the worker can never see
        # the task before the pending row exists. IDs/primitives only.
        transaction.on_commit(
            lambda: run_deep_plan_and_run.delay(
                goal=goal,
                plan_id=plan_id,
                agent_type=agent_type,
                user_id=user_id,
                workspace_id=workspace_id,
                team_id=team_id,
                agent_config=agent_config,
                model_name=model_name,
                sync_to_kanban=sync_to_kanban,
                extra_context=extra_context,
                deep_pack=deep_pack,
            )
        )
