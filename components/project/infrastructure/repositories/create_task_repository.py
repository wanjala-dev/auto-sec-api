"""ORM adapter for task creation.

Extracted from project_controller.py ProjectView.post.
"""

from __future__ import annotations

from components.project.application.ports.create_task_port import (
    CreateTaskCommand,
    CreateTaskPort,
    CreateTaskResult,
)
from components.project.domain.errors import (
    ColumnNotFoundError,
    TaskValidationError,
    TeamMembershipRequiredError,
)


class OrmCreateTaskRepository(CreateTaskPort):
    def create_task(self, *, command: CreateTaskCommand) -> CreateTaskResult:
        from django.db import transaction

        from components.workspace.application.facades.workspace_facade import ensure_workspace_follower
        from infrastructure.persistence.project.models import Column, Project, Task
        from infrastructure.persistence.users.models import CustomUser, UserProfile
        from infrastructure.persistence.workspaces.models import Grant, Workspace

        # ── Resolve column ──────────────────────────────────────────
        try:
            column = Column.objects.select_related("team", "workspace").get(id=command.column_id)
        except Column.DoesNotExist:
            raise ColumnNotFoundError("Invalid column ID.")

        team = column.team
        if team.status != "active":
            raise TaskValidationError("Tasks can only be created on active teams.")

        # ── Membership check ────────────────────────────────────────
        # Workspace admins/owners bypass team-membership (ADR 0002 — RBAC
        # reads WorkspaceMembership.role, never persona). Plain members
        # must be on the team.
        user = CustomUser.objects.filter(id=command.user_id).first()
        if not user:
            raise TeamMembershipRequiredError("User not found.")
        from components.workspace.application.facades.workspace_facade import (
            user_is_workspace_admin_or_owner,
        )

        if not user_is_workspace_admin_or_owner(user, column.workspace):
            if not team.members.filter(id=user.id).exists():
                raise TeamMembershipRequiredError("You must be a member of this team.")

        # ── Resolve project (optional) ──────────────────────────────
        project = None
        if command.project_id:
            try:
                project = Project.objects.get(pk=command.project_id)
            except Project.DoesNotExist:
                raise TaskValidationError("Invalid project ID or the project does not belong to your active team.")
            if project.team_id != team.id:
                raise TaskValidationError("Project does not belong to the specified team.")
            if project.workspace_id != column.workspace_id:
                raise TaskValidationError("Project does not belong to the selected workspace.")

        # ── Resolve grant (optional) ────────────────────────────────
        grant = None
        if command.grant_id:
            try:
                grant = Grant.objects.get(pk=command.grant_id)
            except Grant.DoesNotExist:
                raise TaskValidationError("Invalid grant ID.")
            if grant.workspace_id and column.workspace_id and grant.workspace_id != column.workspace_id:
                raise TaskValidationError("Grant does not belong to the selected workspace.")

        # ── Workspace cross-check ───────────────────────────────────
        if command.workspace_id and str(command.workspace_id) != str(column.workspace_id):
            raise TaskValidationError("Workspace does not match the selected column.")

        # ── Keep user profile in sync ───────────────────────────────
        try:
            userprofile = UserProfile.objects.get(user=user)
            profile_updates = []
            if not userprofile.active_team_id:
                userprofile.active_team_id = team.id
                profile_updates.append("active_team_id")
            if column.workspace_id and not userprofile.active_workspace_id:
                userprofile.active_workspace_id = column.workspace_id
                profile_updates.append("active_workspace_id")
            if profile_updates:
                userprofile.save(update_fields=profile_updates)
        except UserProfile.DoesNotExist:
            pass

        # ── Optional planning fields (task-creation wizard) ─────────
        # Validate up front so a bad value 400s (TaskValidationError)
        # instead of 500ing at the ORM layer. None → model defaults
        # (priority 'medium', no due date). NOTE: Task has its OWN nested
        # Priority enum (low/medium/high/urgent) — distinct from the
        # module-level Project Priority (NP/UR/HI/MD/LO).
        priority = None
        if command.priority:
            code = str(command.priority).strip().lower()
            if code not in Task.Priority.values:
                raise TaskValidationError(
                    f"Invalid priority '{command.priority}'. Use one of: {', '.join(Task.Priority.values)}."
                )
            priority = code

        due_date = None
        if command.due_date:
            from datetime import datetime
            from datetime import time as datetime_time

            from django.utils import timezone as dj_timezone
            from django.utils.dateparse import parse_date, parse_datetime

            raw = str(command.due_date).strip()
            due_date = parse_datetime(raw)
            if due_date is None:
                parsed_day = parse_date(raw)
                if parsed_day is not None:
                    due_date = datetime.combine(parsed_day, datetime_time.min)
            if due_date is None:
                raise TaskValidationError("Invalid due date. Use an ISO date (YYYY-MM-DD) or datetime.")
            if dj_timezone.is_naive(due_date):
                due_date = dj_timezone.make_aware(due_date)

        # ── Create task ─────────────────────────────────────────────
        workspace = column.workspace
        optional_fields = {}
        if priority is not None:
            optional_fields["priority"] = priority
        if due_date is not None:
            optional_fields["due_date"] = due_date
        task = Task.objects.create(
            team=team,
            project=project,
            grant=grant,
            created_by=user,
            title=command.title,
            workspace=workspace,
            column=column,
            source_type=(command.source_type or "")[:64],
            description=command.description or "",
            metadata=command.metadata or {},
            **optional_fields,
        )

        # ── Assign users (optional) ─────────────────────────────────
        # ``assigned_to_ids`` is None for every human-created task (the
        # controller assigns via a separate endpoint). The sign-off
        # materializer passes the workspace owner so a pending sign-off
        # lands on their board pre-assigned. Assignment is a bare M2M
        # add — no team-membership check on assignees (matches
        # AssignUsersToTaskView).
        newly_assigned = []
        assignee_ids = [aid for aid in (command.assigned_to_ids or []) if aid]
        if assignee_ids:
            newly_assigned = list(CustomUser.objects.filter(id__in=assignee_ids))
            if newly_assigned:
                task.assigned_to.add(*newly_assigned)

        # ── Emit workflow event ─────────────────────────────────────
        from components.workflow.infrastructure.adapters.dispatcher import emit_workflow_event

        transaction.on_commit(
            lambda: emit_workflow_event(
                workspace_id=str(task.workspace_id),
                source_type="task",
                trigger_type="task_created",
                payload={
                    "workspace_id": str(task.workspace_id),
                    "user_id": str(user.id),
                    "task_id": str(task.id),
                    "project_id": str(task.project_id) if task.project_id else None,
                    "team_id": str(task.team_id),
                    "target_type": "group",
                    "target_id": str(task.workspace_id),
                },
                source_id=str(task.id),
                idempotency_key=f"task_created:{task.id}",
            )
        )

        # Fire ``task_assigned`` once per assignee, mirroring the normal
        # AssignUsersToTaskView path so workflow automations bound to
        # assignment (e.g. "notify the assignee") still fire for
        # AI-materialized tasks. Bind ``assignee_id`` per-iteration to
        # avoid the classic late-binding closure bug.
        for assignee in newly_assigned:
            assignee_id = str(assignee.id)
            transaction.on_commit(
                lambda assignee_id=assignee_id: emit_workflow_event(
                    workspace_id=str(task.workspace_id),
                    source_type="task",
                    trigger_type="task_assigned",
                    payload={
                        "workspace_id": str(task.workspace_id),
                        "user_id": str(user.id),
                        "task_id": str(task.id),
                        "project_id": str(task.project_id) if task.project_id else None,
                        "team_id": str(task.team_id),
                        "assignee_id": assignee_id,
                        "task_source_type": task.source_type or "",
                        "target_type": "group",
                        "target_id": str(task.workspace_id),
                    },
                    source_id=str(task.id),
                    idempotency_key=f"task_assigned:{task.id}:{assignee_id}",
                )
            )

        # ── Auto-follow workspaces ──────────────────────────────────
        workspace_ids_to_follow = {sid for sid in (task.workspace_id, column.workspace_id) if sid}
        if workspace_ids_to_follow:
            for workspace_obj in Workspace.objects.filter(id__in=workspace_ids_to_follow):
                ensure_workspace_follower(workspace_obj, user)

        return CreateTaskResult(
            task_id=str(task.pk),
            team_id=str(task.team.id),
            workspace_id=str(task.workspace_id) if task.workspace_id else "",
            created_by=str(task.created_by.id),
            updated_at=task.updated_at.isoformat(),
            title=task.title,
            created_at=task.created_at.isoformat(),
            project_id=str(task.project.id) if task.project else None,
            grant_id=str(task.grant.id) if task.grant else None,
            status=task.status,
            column_id=str(task.column.id),
            order=task.order,
            description=task.description or "",
            due_date=task.due_date.isoformat() if task.due_date else None,
            priority=task.priority or "",
            assigned_to_ids=[str(u.id) for u in newly_assigned],
        )
