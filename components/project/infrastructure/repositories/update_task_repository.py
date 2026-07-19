"""ORM adapter for task update (patch) operations.

Extracted from project_controller.py TaskDetailView.patch.
"""
from __future__ import annotations

from components.project.domain.errors import (
    TaskNotFoundError,
    TaskValidationError,
    TeamMembershipRequiredError,
    WorkspaceMembershipRequiredError,
)
from components.project.application.ports.update_task_port import (
    UpdateTaskCommand,
    UpdateTaskPort,
    UpdateTaskResult,
)


class OrmUpdateTaskRepository(UpdateTaskPort):

    def update_task(self, *, command: UpdateTaskCommand) -> UpdateTaskResult:
        from django.db import transaction
        from infrastructure.persistence.project.models import Task
        from components.project.mappers.rest.project_serializers import TaskSerializer
        from infrastructure.persistence.users.models import CustomUser, UserProfile
        from components.workspace.application.facades.workspace_facade import user_is_workspace_member

        # ── Resolve user ────────────────────────────────────────────
        user = CustomUser.objects.filter(id=command.user_id).first()
        if not user:
            raise TeamMembershipRequiredError("User not found.")

        # ── Resolve task ────────────────────────────────────────────
        try:
            task = Task.objects.select_related("team", "team__workspace", "workspace").get(pk=command.task_id)
        except Task.DoesNotExist:
            raise TaskNotFoundError(f"Task with ID {command.task_id} not found.")

        # ── Workspace membership ────────────────────────────────────
        if not user_is_workspace_member(user, task.workspace):
            raise WorkspaceMembershipRequiredError(
                "You must belong to the organization to perform this action."
            )

        # ── Team membership ─────────────────────────────────────────
        # Workspace admins/owners bypass team membership (ADR 0002).
        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_admin_or_owner,
        )
        if not user_is_workspace_admin_or_owner(user, task.workspace):
            if not task.team.members.filter(id=user.id).exists():
                raise TeamMembershipRequiredError(
                    "You must be a member of the task's team to update it."
                )

        # ── Keep user profile in sync ───────────────────────────────
        try:
            userprofile = UserProfile.objects.get(user=user)
            profile_updates = []
            if task.workspace_id and not userprofile.active_workspace_id:
                userprofile.active_workspace_id = task.workspace_id
                profile_updates.append("active_workspace_id")
            if not userprofile.active_team_id and task.team.members.filter(id=user.id).exists():
                userprofile.active_team_id = task.team_id
                profile_updates.append("active_team_id")
            if profile_updates:
                userprofile.save(update_fields=profile_updates)
        except UserProfile.DoesNotExist:
            pass

        # ── Partial update ──────────────────────────────────────────
        serializer = TaskSerializer(
            task,
            data=command.data,
            partial=True,
            context={"request": command.http_request} if command.http_request else {},
        )
        if not serializer.is_valid():
            raise TaskValidationError(str(serializer.errors))

        previous_status = task.status
        previous_column_id = task.column_id
        serializer.save()

        # Re-read the fields we'll close over for the on_commit callbacks
        # so they reflect the post-save state without a query.
        new_status = task.status
        new_column_id = task.column_id

        # ── Emit workflow event on completion ───────────────────────
        if previous_status != Task.DONE and new_status == Task.DONE:
            from components.workflow.infrastructure.adapters.dispatcher import emit_workflow_event

            transaction.on_commit(
                lambda: emit_workflow_event(
                    workspace_id=str(task.workspace_id),
                    source_type="task",
                    trigger_type="task_completed",
                    payload={
                        "workspace_id": str(task.workspace_id),
                        "user_id": str(user.id),
                        "task_id": str(task.id),
                        "project_id": str(task.project_id) if task.project_id else None,
                        "team_id": str(task.team_id),
                        "assignee_id": str(user.id),
                        "target_type": "group",
                        "target_id": str(task.workspace_id),
                    },
                    source_id=str(task.id),
                    idempotency_key=f"task_completed:{task.id}",
                )
            )

        # ── Emit workflow event on column change (Phase 4) ──────────
        # Fires whenever the FK actually moved. Idempotency key
        # includes new_column_id + updated_at so two distinct moves on
        # the same task in the same hour still produce two events.
        if previous_column_id is not None and previous_column_id != new_column_id:
            from components.workflow.infrastructure.adapters.dispatcher import emit_workflow_event

            transaction.on_commit(
                lambda: emit_workflow_event(
                    workspace_id=str(task.workspace_id),
                    source_type="task",
                    trigger_type="task_moved_column",
                    payload={
                        "workspace_id": str(task.workspace_id),
                        "user_id": str(user.id),
                        "task_id": str(task.id),
                        "project_id": str(task.project_id) if task.project_id else None,
                        "team_id": str(task.team_id),
                        "previous_column_id": str(previous_column_id),
                        "new_column_id": str(new_column_id) if new_column_id else None,
                        "task_source_type": task.source_type or "",
                        "target_type": "group",
                        "target_id": str(task.workspace_id),
                    },
                    source_id=str(task.id),
                    idempotency_key=(
                        f"task_moved_column:{task.id}:{new_column_id}:"
                        f"{task.updated_at.isoformat()}"
                    ),
                )
            )

        return UpdateTaskResult(success=True, task=serializer.data)
