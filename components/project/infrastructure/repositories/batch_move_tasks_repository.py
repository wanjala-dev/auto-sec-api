"""ORM adapter for batch task move operations."""
from __future__ import annotations

from components.project.domain.errors import (
    TaskNotFoundError,
    TeamMembershipRequiredError,
    WorkspaceMembershipRequiredError,
)
from components.project.application.ports.batch_move_tasks_port import (
    BatchMoveTasksCommand,
    BatchMoveTasksPort,
    BatchMoveTasksResult,
)


class OrmBatchMoveTasksRepository(BatchMoveTasksPort):

    def batch_move_tasks(self, *, command: BatchMoveTasksCommand) -> BatchMoveTasksResult:
        from django.db import transaction
        from infrastructure.persistence.project.models import Column, Task
        from infrastructure.persistence.users.models import CustomUser
        from components.workspace.application.facades.workspace_facade import user_is_workspace_member

        # ── Resolve user ────────────────────────────────────────────
        user = CustomUser.objects.filter(id=command.user_id).first()
        if not user:
            raise TeamMembershipRequiredError("User not found.")

        is_privileged = getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)

        # ── Resolve all tasks in one query ──────────────────────────
        task_ids = [m.task_id for m in command.moves]
        tasks = Task.objects.select_related(
            "team", "workspace", "column",
        ).filter(pk__in=task_ids)
        task_map = {str(t.pk): t for t in tasks}

        missing = [tid for tid in task_ids if tid not in task_map]
        if missing:
            raise TaskNotFoundError(f"Tasks not found: {', '.join(missing)}")

        # ── Resolve all target columns in one query ─────────────────
        column_ids = {m.column_id for m in command.moves}
        columns = Column.objects.select_related("team", "workspace").filter(pk__in=column_ids)
        column_map = {str(c.pk): c for c in columns}

        missing_cols = [cid for cid in column_ids if cid not in column_map]
        if missing_cols:
            raise TaskNotFoundError(f"Columns not found: {', '.join(missing_cols)}")

        # ── Validate membership (check each unique workspace/team) ──
        checked_teams = set()
        for task in task_map.values():
            team_id = task.team_id
            if team_id in checked_teams:
                continue
            checked_teams.add(team_id)

            if not is_privileged:
                if not user_is_workspace_member(user, task.workspace):
                    raise WorkspaceMembershipRequiredError(
                        "You must belong to the organization to perform this action."
                    )
                # Workspace admins/owners bypass team membership (ADR 0002).
                from components.workspace.application.facades.workspace_facade import (
                    user_is_workspace_admin_or_owner,
                )
                if not user_is_workspace_admin_or_owner(user, task.workspace):
                    if not task.team.members.filter(id=user.id).exists():
                        raise TeamMembershipRequiredError(
                            "You must be a member of the task's team to update it."
                        )

        # ── Apply moves ─────────────────────────────────────────────
        # Capture previous_column_id BEFORE we overwrite task.column;
        # the Phase 4 ``task_moved_column`` workflow trigger needs both
        # endpoints. The previous Phase-0 emit branch relied on
        # ``task._previous_status`` which nothing ever set — that
        # branch never fired in production. Removed.
        from datetime import datetime, timezone

        tasks_to_update = []
        previous_column_by_task: dict[str, str | None] = {}

        for move in command.moves:
            task = task_map[move.task_id]
            target_column = column_map[move.column_id]

            previous_column_by_task[str(task.id)] = (
                str(task.column_id) if task.column_id else None
            )
            task.column = target_column
            if move.order is not None:
                task.order = move.order

            tasks_to_update.append(task)

        moved_at_iso = datetime.now(timezone.utc).isoformat()
        with transaction.atomic():
            Task.objects.bulk_update(tasks_to_update, ["column", "order"])

            # ── Emit workflow events for column moves ────────────────
            # Every task in this batch had its column changed by
            # definition. Idempotency key includes the new column +
            # batch timestamp so two distinct batches that both move
            # a task to the same column still produce two events.
            from components.workflow.infrastructure.adapters.dispatcher import emit_workflow_event

            for task in tasks_to_update:
                previous_column_id = previous_column_by_task[str(task.id)]
                if previous_column_id == str(task.column_id):
                    # Move was a no-op (target column equals current).
                    continue

                transaction.on_commit(
                    lambda t=task, prev=previous_column_id: emit_workflow_event(
                        workspace_id=str(t.workspace_id),
                        source_type="task",
                        trigger_type="task_moved_column",
                        payload={
                            "workspace_id": str(t.workspace_id),
                            "user_id": str(user.id),
                            "task_id": str(t.id),
                            "project_id": str(t.project_id) if t.project_id else None,
                            "team_id": str(t.team_id),
                            "previous_column_id": prev,
                            "new_column_id": str(t.column_id),
                            "task_source_type": t.source_type or "",
                            "target_type": "group",
                            "target_id": str(t.workspace_id),
                        },
                        source_id=str(t.id),
                        idempotency_key=(
                            f"task_moved_column:{t.id}:{t.column_id}:{moved_at_iso}"
                        ),
                    )
                )

        return BatchMoveTasksResult(
            success=True,
            updated_count=len(tasks_to_update),
        )
