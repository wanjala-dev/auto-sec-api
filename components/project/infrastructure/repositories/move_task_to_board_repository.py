"""ORM adapter for moving a task to a different board.

Reassigns team + project + column atomically so a card can cross boards
without leaving ``team`` / ``project`` stale. The destination board is the
target column's own team + project — deriving them from the column is what
guarantees the three FKs stay consistent. Membership is validated against the
DESTINATION board (mirrors ``OrmBatchMoveTasksRepository`` and ADR 0002:
workspace admins/owners bypass team membership).
"""

from __future__ import annotations

from datetime import UTC

from components.project.application.ports.move_task_to_board_port import (
    MoveTaskToBoardCommand,
    MoveTaskToBoardPort,
    MoveTaskToBoardResult,
)
from components.project.domain.errors import (
    TaskNotFoundError,
    TaskValidationError,
    TeamMembershipRequiredError,
    WorkspaceMembershipRequiredError,
)


class OrmMoveTaskToBoardRepository(MoveTaskToBoardPort):
    def move_task_to_board(self, *, command: MoveTaskToBoardCommand) -> MoveTaskToBoardResult:
        from datetime import datetime

        from django.db import transaction

        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_admin_or_owner,
            user_is_workspace_member,
        )
        from infrastructure.persistence.project.models import Column, Task
        from infrastructure.persistence.users.models import CustomUser

        # ── Resolve user ────────────────────────────────────────────
        user = CustomUser.objects.filter(id=command.user_id).first()
        if not user:
            raise TeamMembershipRequiredError("User not found.")
        is_privileged = getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)

        # ── Resolve task + destination column ───────────────────────
        task = Task.objects.select_related("team", "workspace", "column", "project").filter(pk=command.task_id).first()
        if task is None:
            raise TaskNotFoundError(f"Task not found: {command.task_id}")

        target_column = (
            Column.objects.select_related("team", "workspace", "project")
            .filter(pk=command.target_column_id, is_deleted=False)
            .first()
        )
        if target_column is None:
            raise TaskNotFoundError(f"Column not found: {command.target_column_id}")

        # ── Destination board is the column's own team + project ────
        dest_team = target_column.team
        dest_project = target_column.project  # may be None (team-level board)

        # A task never leaves its workspace; cross-workspace moves are
        # rejected outright (isolation is load-bearing for a security tool).
        if str(target_column.workspace_id) != str(task.workspace_id):
            raise TaskValidationError("The destination column belongs to a different workspace.")

        # ── Validate membership against the DESTINATION board ───────
        if not is_privileged:
            if not user_is_workspace_member(user, target_column.workspace):
                raise WorkspaceMembershipRequiredError("You must belong to the organization to perform this action.")
            # Workspace admins/owners bypass team membership (ADR 0002).
            if not user_is_workspace_admin_or_owner(user, target_column.workspace):
                if not dest_team.members.filter(id=user.id).exists():
                    raise TeamMembershipRequiredError("You must be a member of the destination board's team.")

        previous_column_id = str(task.column_id) if task.column_id else None
        moved_at_iso = datetime.now(UTC).isoformat()

        with transaction.atomic():
            task.team = dest_team
            task.project = dest_project
            task.column = target_column
            if command.order is not None:
                task.order = command.order
            task.save(update_fields=["team", "project", "column", "order", "updated_at"])

            # Emit the same ``task_moved_column`` workflow event the batch-move
            # path emits, so cross-board moves are observable to the engine.
            if previous_column_id != str(task.column_id):
                from components.workflow.application.providers.workflow_dispatcher_provider import (
                    get_workflow_dispatcher_provider,
                )

                transaction.on_commit(
                    lambda t=task, prev=previous_column_id: get_workflow_dispatcher_provider().emit_workflow_event(
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
                        idempotency_key=f"task_moved_column:{t.id}:{t.column_id}:{moved_at_iso}",
                    )
                )

        return MoveTaskToBoardResult(
            task_id=str(task.id),
            team_id=str(task.team_id),
            project_id=str(task.project_id) if task.project_id else None,
            column_id=str(task.column_id),
            order=task.order,
        )
