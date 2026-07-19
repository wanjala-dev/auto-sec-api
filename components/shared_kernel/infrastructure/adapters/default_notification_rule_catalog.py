from __future__ import annotations

from components.notifications.infrastructure.adapters.notification_service import (
    resolve_actor,
    workspace_recipient_builder,
)
from components.shared_kernel.application.providers.notification_signal_provider import (
    NotificationSignalProvider,
)
from components.shared_kernel.infrastructure.adapters.django_model_notification_registry import (
    NotificationRule,
)
from infrastructure.persistence.project.models import Project, ProjectUpdate, Task, TaskComment
from infrastructure.persistence.team.models import Team
from infrastructure.persistence.workspaces.models import Workspace

# NOTE: The nonprofit/commerce contexts (budgeting, sponsorship, marketplace,
# workspaces.news) were removed from this fork, so their notification rules and
# the models they referenced (Budget, Transaction, Campaign, Donation, Event,
# Goal, Recipient, RecipientUpdate, Product, Cart, CartItem, News, NewsComment)
# are no longer part of the default catalog. Only rules for KEPT models remain.

_REGISTERED = False
notification_signal_provider = NotificationSignalProvider()


def _workspace_recipients(workspace: Workspace):
    builder = workspace_recipient_builder(workspace)
    builder.add(getattr(workspace, "shared_user", None))
    return builder.build()


def _project_recipients(project: Project):
    builder = workspace_recipient_builder(project.workspace)
    builder.add(project.created_by)
    builder.add(project.lead)
    if project.team:
        builder.add_queryset(project.team.members.all())
    return builder.build()


def _project_update_recipients(update: ProjectUpdate):
    builder = workspace_recipient_builder(update.workspace)
    builder.add(update.author)
    project = update.Project
    builder.add(getattr(project, "created_by", None))
    builder.add(getattr(project, "lead", None))
    if project and project.team:
        builder.add_queryset(project.team.members.all())
    return builder.build()


def _task_recipients(task: Task):
    builder = workspace_recipient_builder(task.workspace)
    builder.add(task.created_by)
    builder.add_queryset(task.assigned_to.all())
    if task.team:
        builder.add_queryset(task.team.members.all())
    return builder.build()


def _task_comment_recipients(comment: TaskComment):
    task = comment.task
    builder = workspace_recipient_builder(task.workspace)
    builder.add(comment.author)
    builder.add(task.created_by)
    builder.add_queryset(task.assigned_to.all())
    if task.team:
        builder.add_queryset(task.team.members.all())
    return builder.build()


def _team_recipients(team: Team):
    builder = workspace_recipient_builder(team.workspace)
    builder.add(team.created_by)
    builder.add_queryset(team.members.all())
    return builder.build()


def register_default_notification_rules() -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    notification_signal_provider.register_notification_rule(
        NotificationRule(
            model=Workspace,
            namespace="workspace",
            workspace_getter=lambda obj: obj,
            label_getter=lambda obj: obj.workspace_name or str(obj.pk),
            recipients_getter=_workspace_recipients,
            field_event_map={
                "status": "status_changed",
                "is_active": "active_changed",
                "notifications_enabled": "notification_toggle",
                "ai_teammate_enabled": "ai_teammate_toggle",
            },
            verb_templates={
                "workspaces.created": 'created workspace "{label}"',
                "workspaces.updated": 'updated workspace "{label}"',
                "workspaces.deleted": 'deleted workspace "{label}"',
                "workspaces.status_changed": 'changed workspace "{label}" status to {status}',
                "workspaces.active_changed": 'updated workspace "{label}" active state to {is_active}',
                "workspaces.notification_toggle": 'toggled notifications for "{label}" to {notifications_enabled}',
                "workspaces.ai_teammate_toggle": 'set Orchestrator agent for "{label}" to {ai_teammate_enabled}',
            },
            include_default_metadata=True,
        )
    )

    notification_signal_provider.register_notification_rule(
        NotificationRule(
            model=Project,
            namespace="projects",
            workspace_getter=lambda obj: obj.workspace,
            label_getter=lambda obj: obj.title,
            recipients_getter=_project_recipients,
            field_event_map={"status": "status_changed"},
            verb_templates={
                "projects.created": 'created project "{label}"',
                "projects.updated": 'updated project "{label}"',
                "projects.deleted": 'deleted project "{label}"',
                "projects.status_changed": 'changed project "{label}" status to {status}',
            },
        )
    )

    notification_signal_provider.register_notification_rule(
        NotificationRule(
            model=ProjectUpdate,
            namespace="project_updates",
            workspace_getter=lambda obj: obj.workspace,
            label_getter=lambda obj: obj.Update[:80],
            recipients_getter=_project_update_recipients,
            verb_templates={
                "project_updates.created": 'posted a project update "{label}"',
                "project_updates.updated": 'edited project update "{label}"',
                "project_updates.deleted": 'deleted project update "{label}"',
            },
        )
    )

    notification_signal_provider.register_notification_rule(
        NotificationRule(
            model=Task,
            namespace="tasks",
            workspace_getter=lambda obj: obj.workspace,
            label_getter=lambda obj: obj.title,
            recipients_getter=_task_recipients,
            field_event_map={"status": "status_changed"},
            verb_templates={
                "tasks.created": 'created task "{label}"',
                "tasks.updated": 'updated task "{label}"',
                "tasks.deleted": 'deleted task "{label}"',
                "tasks.status_changed": 'changed task "{label}" status to {status}',
            },
        )
    )

    notification_signal_provider.register_notification_rule(
        NotificationRule(
            model=TaskComment,
            namespace="tasks.comment",
            workspace_getter=lambda obj: obj.task.workspace,
            label_getter=lambda obj: obj.comment[:80],
            recipients_getter=_task_comment_recipients,
            base_events=("created", "deleted"),
            verb_templates={
                "tasks.comment.created": 'commented on task "{label}"',
                "tasks.comment.deleted": 'deleted a task comment "{label}"',
            },
        )
    )

    notification_signal_provider.register_notification_rule(
        NotificationRule(
            model=Team,
            namespace="teams",
            workspace_getter=lambda obj: obj.workspace,
            label_getter=lambda obj: obj.title,
            recipients_getter=_team_recipients,
            field_event_map={"status": "status_changed"},
            verb_templates={
                "teams.created": 'created team "{label}"',
                "teams.updated": 'updated team "{label}"',
                "teams.deleted": 'deleted team "{label}"',
                "teams.status_changed": 'changed team "{label}" status to {status}',
            },
        )
    )

    notification_signal_provider.connect_task_assignment_signal(
        task_model=Task,
        actor_resolver=resolve_actor,
    )
