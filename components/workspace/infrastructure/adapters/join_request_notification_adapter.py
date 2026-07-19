"""Notification adapter for workspace join request events.

Converts domain events into in-app notifications via the shared
``NotificationDispatcher``. Email integration can be layered on top
later by hooking into the same dispatch metadata.
"""

from __future__ import annotations

import logging

from infrastructure.persistence.notifications.models import Notification
from components.notifications.infrastructure.adapters.notification_service import (
    NotificationDispatcher,
)

logger = logging.getLogger(__name__)


def _display_name(user) -> str:
    if not user:
        return "Someone"
    full = getattr(user, "get_full_name", lambda: "")() or ""
    return (
        full.strip()
        or getattr(user, "username", None)
        or getattr(user, "email", None)
        or "Someone"
    )


class JoinRequestNotificationAdapter:
    """Dispatches in-app notifications + transactional emails for join request
    lifecycle events.

    In-app notifications go through the shared ``NotificationDispatcher``;
    emails reuse the platform ``send_email`` facade (same path as donation
    admin alerts and team invitations).
    """

    def __init__(self, dispatcher: NotificationDispatcher | None = None) -> None:
        self._dispatcher = dispatcher or NotificationDispatcher()

    # ── email ────────────────────────────────────────────────────────
    #
    # Reuse the shared EmailSendingPort (same path as sharing/grants/receipts):
    # ``send_templated`` resolves DEFAULT_FROM_EMAIL, renders the HTML, and
    # derives the plain-text body — so we never re-derive from_email/text here.

    def _send_email(self, *, to_email, subject, template, context) -> None:
        if not to_email:
            return
        try:
            from components.shared_platform.application.providers.email_adapter_provider import (
                get_email_adapter_provider,
            )

            get_email_adapter_provider().adapter().send_templated(
                to=[to_email],
                subject=subject,
                template=template,
                context=context,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to send join-request email to=%s template=%s",
                to_email,
                template,
            )

    def _site_context(self, workspace):
        """(site_name, dashboard_url) using the canonical frontend-base helper."""
        from django.conf import settings
        from components.shared_platform.infrastructure.services.core_utils import (
            resolve_frontend_base_url,
        )

        site_name = getattr(settings, "SITE_NAME", "Octopus")
        try:
            base_url = (resolve_frontend_base_url() or "").rstrip("/")
        except Exception:  # noqa: BLE001
            base_url = ""
        dashboard_url = f"{base_url}/dashboard/{workspace.id}" if base_url else ""
        return site_name, dashboard_url

    def _workspace_owner_and_admins(self, workspace):
        """Recipients for owner-side notifications.

        Includes the workspace owner plus any active admins. De-duplicated
        on the way in so a workspace owner who also has an explicit admin
        membership row only gets one notification.
        """
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        recipients = []
        seen: set = set()
        owner = getattr(workspace, "workspace_owner", None)
        if owner and owner.id not in seen:
            recipients.append(owner)
            seen.add(owner.id)

        admin_memberships = WorkspaceMembership.objects.filter(
            workspace_id=workspace.id,
            status=WorkspaceMembership.Status.ACTIVE,
            role=WorkspaceMembership.Role.ADMIN,
        ).select_related("user")
        for membership in admin_memberships:
            user = membership.user
            if not user or user.id in seen:
                continue
            recipients.append(user)
            seen.add(user.id)
        return recipients

    def notify_created(self, *, event, workspace, requester) -> None:
        recipients = self._workspace_owner_and_admins(workspace)
        recipients = [r for r in recipients if r and r.id != requester.id]
        if not recipients:
            return

        try:
            self._dispatcher.dispatch(
                actor=requester,
                workspace=workspace,
                verb="requested to join",
                notification_type=Notification.NotificationType.SYSTEM,
                recipients=recipients,
                metadata={
                    "event": "workspace.join_request.created",
                    "join_request_id": str(event.request_id),
                    "workspace_id": str(event.workspace_id),
                    "requester_id": str(event.requester_id),
                    "message": event.message or "",
                },
                target=workspace,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to dispatch workspace.join_request.created notification "
                "for request=%s workspace=%s",
                event.request_id,
                event.workspace_id,
            )

        # Email the workspace owner/admins so they know to review the request.
        site_name, dashboard_url = self._site_context(workspace)
        workspace_name = workspace.workspace_name or "your workspace"
        requester_name = _display_name(requester)
        for recipient in recipients:
            self._send_email(
                to_email=getattr(recipient, "email", ""),
                subject=f"{requester_name} requested to join {workspace_name}",
                template="workspace/email_join_request.html",
                context={
                    "site_name": site_name,
                    "requester_name": requester_name,
                    "workspace_name": workspace_name,
                    "review_url": dashboard_url,
                },
            )

    def notify_approved(self, *, event, workspace, requester, reviewer) -> None:
        if not requester:
            return
        try:
            self._dispatcher.dispatch(
                actor=reviewer,
                workspace=workspace,
                verb=f'approved your request to join "{workspace.workspace_name or "a workspace"}"',
                notification_type=Notification.NotificationType.SYSTEM,
                recipients=[requester],
                metadata={
                    "event": "workspace.join_request.approved",
                    "join_request_id": str(event.request_id),
                    "workspace_id": str(event.workspace_id),
                    "reviewer_id": str(event.reviewer_id),
                    "note": event.note or "",
                },
                target=workspace,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to dispatch workspace.join_request.approved notification "
                "for request=%s",
                event.request_id,
            )

        # Email the requester that they're in.
        site_name, dashboard_url = self._site_context(workspace)
        workspace_name = workspace.workspace_name or "the workspace"
        self._send_email(
            to_email=getattr(requester, "email", ""),
            subject=f"You're in — your request to join {workspace_name} was approved",
            template="workspace/email_join_request_approved.html",
            context={
                "site_name": site_name,
                "requester_name": _display_name(requester),
                "workspace_name": workspace_name,
                "dashboard_url": dashboard_url,
            },
        )

    def notify_denied(self, *, event, workspace, requester, reviewer) -> None:
        if not requester:
            return
        try:
            self._dispatcher.dispatch(
                actor=reviewer,
                workspace=workspace,
                verb=f'declined your request to join "{workspace.workspace_name or "a workspace"}"',
                notification_type=Notification.NotificationType.SYSTEM,
                recipients=[requester],
                metadata={
                    "event": "workspace.join_request.denied",
                    "join_request_id": str(event.request_id),
                    "workspace_id": str(event.workspace_id),
                    "reviewer_id": str(event.reviewer_id),
                    "note": event.note or "",
                },
                target=workspace,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to dispatch workspace.join_request.denied notification "
                "for request=%s",
                event.request_id,
            )
