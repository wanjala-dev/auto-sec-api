from __future__ import annotations

from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from infrastructure.persistence.broadcast.models import Banner
from infrastructure.persistence.workspaces.models import Workspace
from components.workspace.application.providers.workspace_setup_query_provider import (
    WorkspaceSetupQueryProvider,
)


@shared_task(
    name='infrastructure.workspaces.tasks.sync_workspace_setup_banners',
    soft_time_limit=240,
    time_limit=300,
)
def sync_workspace_setup_banners() -> int:
    """Ensure onboarding banners reflect each workspace's current setup state.

    Returns the number of banners that were created or updated.
    """
    now = timezone.now()
    updated_count = 0
    workspace_setup_query_service = WorkspaceSetupQueryProvider().build_service()

    queryset = workspace_setup_query_service.annotate_setup_state(
        Workspace.objects.filter(is_active=True).prefetch_related("contribution_means")
    )

    for workspace in queryset.iterator(chunk_size=100):
        results = workspace_setup_query_service.get_setup_results(workspace)
        for result in results:
            definition = result.definition
            title = definition.title()
            message = definition.message()

            banner, _created = Banner.objects.get_or_create(
                scope=Banner.Scope.WORKSPACE,
                workspace=workspace,
                title=title,
                defaults={
                    "message": message,
                    "severity": definition.severity,
                    "dismissible": definition.dismissible,
                    "priority": definition.priority,
                    "is_active": not result.is_complete,
                    "starts_at": now,
                },
            )

            if result.is_complete:
                if banner.is_active:
                    banner.is_active = False
                    banner.ends_at = now
                    banner.save(update_fields=["is_active", "ends_at"])
                    updated_count += 1
                continue

            updates = []
            if banner.message != message:
                banner.message = message
                updates.append("message")
            if banner.severity != definition.severity:
                banner.severity = definition.severity
                updates.append("severity")
            if banner.dismissible != definition.dismissible:
                banner.dismissible = definition.dismissible
                updates.append("dismissible")
            if banner.priority != definition.priority:
                banner.priority = definition.priority
                updates.append("priority")
            if not banner.is_active:
                banner.is_active = True
                updates.append("is_active")
            if banner.ends_at is not None:
                banner.ends_at = None
                updates.append("ends_at")
            if banner.starts_at is None:
                banner.starts_at = now
                updates.append("starts_at")

            if updates:
                banner.save(update_fields=updates)
                updated_count += 1

    return updated_count


@shared_task(
    name='infrastructure.workspaces.tasks.prune_temporary_workspaces',
    soft_time_limit=240,
    time_limit=300,
)
def prune_temporary_workspaces(max_age_minutes: int = 60) -> int:
    """Delete stale temporary workspaces created during onboarding flows.

    Workspaces whose name starts with ``temp-workspace-`` and have not been updated within
    ``max_age_minutes`` are purged to prevent the table from filling up with
    abandoned scaffolding records.
    """
    cutoff = timezone.now() - timedelta(minutes=max_age_minutes)
    queryset = Workspace.objects.filter(
        workspace_name__startswith="temp-workspace-",
        updated_at__lt=cutoff,
    )

    workspace_count = queryset.count()
    if not workspace_count:
        return 0

    queryset.delete()
    return workspace_count


@shared_task(
    name='infrastructure.workspaces.tasks.expire_support_impersonation_sessions',
    soft_time_limit=60,
    time_limit=90,
)
def expire_support_impersonation_sessions() -> int:
    """Clean up SupportImpersonationSessions that have passed their TTL.

    For each session where ``expires_at`` is in the past and
    ``ended_at`` is null, deletes the linked synthetic
    ``WorkspaceMembership`` row (the one with ``is_impersonation=True``)
    and stamps ``ended_at`` so the session shows as ended in audit
    queries. Idempotent — re-running the task does nothing once a
    session is already marked ended.

    Returns the number of sessions that were expired in this run.
    """
    from django.db import transaction as db_transaction
    from infrastructure.persistence.workspaces.models import (
        SupportImpersonationSession,
        WorkspaceMembership,
    )

    now = timezone.now()
    stale = list(
        SupportImpersonationSession.objects.filter(
            ended_at__isnull=True,
            expires_at__lte=now,
        ).only("id", "synthetic_membership_id")
    )
    if not stale:
        return 0

    expired = 0
    for session in stale:
        with db_transaction.atomic():
            if session.synthetic_membership_id:
                WorkspaceMembership.objects.filter(
                    id=session.synthetic_membership_id
                ).delete()
            SupportImpersonationSession.objects.filter(id=session.id).update(
                synthetic_membership=None,
                ended_at=now,
            )
        expired += 1
    return expired
