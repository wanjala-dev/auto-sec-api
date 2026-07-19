"""ORM adapter implementing LoginActivityQueryPort.

Returns querysets (sliceable — DRF paginates them) with the FKs the
serializers read eager-loaded (``session`` for the self view;
``session`` + ``user`` for the workspace view) so a page serialises at
a constant query count.

Workspace scoping uses uncorrelated ``__in`` subqueries for the ACTIVE
member ids and the workspace owner id, so membership resolution rides
the main query instead of materialising member lists in Python.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import Q

from components.identity.application.ports.login_activity_query_port import LoginActivityQueryPort
from components.identity.application.queries.login_activity_query import LoginActivityQuery
from components.identity.application.queries.workspace_login_activity_query import WorkspaceLoginActivityQuery
from components.identity.domain.enums import LOGIN_ACTIVITY_EVENT_CODES


def _apply_shared_filters(queryset, query):
    """event_code / success / created bounds — shared by both scopes."""
    if query.event_code:
        queryset = queryset.filter(event_code=query.event_code)
    if query.success is not None:
        queryset = queryset.filter(success=query.success)
    if query.created_from is not None:
        queryset = queryset.filter(created_at__gte=query.created_from)
    if query.created_to is not None:
        queryset = queryset.filter(created_at__lte=query.created_to)
    return queryset


class OrmLoginActivityRepository(LoginActivityQueryPort):
    """Concrete login-activity read model backed by the Django ORM."""

    def list_for_user(self, query: LoginActivityQuery):
        from infrastructure.persistence.users.models import AuthAuditEvent

        queryset = (
            AuthAuditEvent.objects.filter(user_id=query.user_id).select_related("session").order_by("-created_at")
        )
        return _apply_shared_filters(queryset, query)

    def list_for_workspace(self, query: WorkspaceLoginActivityQuery):
        from infrastructure.persistence.users.models import AuthAuditEvent

        queryset = (
            AuthAuditEvent.objects.filter(
                self._workspace_member_q(query.workspace_id),
                event_code__in=LOGIN_ACTIVITY_EVENT_CODES,
            )
            .exclude(workspace_exclusions__workspace_id=query.workspace_id)
            .select_related("session", "user")
            .order_by("-created_at")
        )
        if query.user_id is not None:
            queryset = queryset.filter(user_id=query.user_id)
        return _apply_shared_filters(queryset, query)

    def list_active_workspace_sessions(self, *, workspace_id: UUID, limit: int = 200):
        from django.utils import timezone

        from infrastructure.persistence.users.models import UserSession

        return (
            UserSession.objects.filter(
                self._workspace_member_q(workspace_id),
                revoked_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .select_related("user")
            .order_by("-last_seen_at")[:limit]
        )

    def get_workspace_event(self, *, workspace_id: UUID, event_id: int):
        from infrastructure.persistence.users.models import AuthAuditEvent

        # Intentionally NOT filtered by this workspace's exclusions —
        # hiding an already-hidden event must stay an idempotent 204.
        return AuthAuditEvent.objects.filter(
            self._workspace_member_q(workspace_id),
            id=event_id,
            event_code__in=LOGIN_ACTIVITY_EVENT_CODES,
        ).first()

    @staticmethod
    def _workspace_member_q(workspace_id: UUID) -> Q:
        """ACTIVE members OR the workspace owner (who may hold no
        membership row) — both as subqueries, mirroring how
        ``IsWorkspaceAdmin`` treats owners."""
        from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership

        member_ids = WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            status=WorkspaceMembership.Status.ACTIVE,
        ).values("user_id")
        owner_id = Workspace.objects.filter(id=workspace_id).values("workspace_owner_id")
        return Q(user_id__in=member_ids) | Q(user_id__in=owner_id)
