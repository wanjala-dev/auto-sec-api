"""SoftDeletePort adapter for org-level login-activity "deletes".

The trashable entity is the ``WorkspaceLoginActivityExclusion`` row —
its EXISTENCE is the soft-deleted state (the event is hidden from that
workspace's org view while the row exists). The append-only
``AuthAuditEvent`` is NEVER touched by any of these operations: the
member keeps their own history and other workspaces are unaffected.

Lifecycle wiring (see ``TrashWorkspaceLoginActivityUseCase``):
- The trash use case CREATES the exclusion row first, then records the
  bin entry; the bin's ``soft_delete`` callback therefore only builds
  the human-readable display snapshot — the hide already happened.
- ``restore`` deletes the exclusion row → the event reappears in the
  workspace's login-activity list.
- ``hard_delete`` permanently deletes the exclusion row ONLY (the hide
  becomes non-restorable; the audit event itself always survives).
"""

from __future__ import annotations

import logging

from components.recycle_bin.application.ports.soft_delete_port import SoftDeletePort

logger = logging.getLogger(__name__)


class LoginActivitySoftDeleteAdapter(SoftDeletePort):
    def soft_delete(self, entity_id: str) -> dict:
        from infrastructure.persistence.users.models import WorkspaceLoginActivityExclusion

        exclusion = WorkspaceLoginActivityExclusion.objects.select_related(
            "event__user",
            "event__session",
        ).get(id=entity_id)
        event = exclusion.event
        user = event.user
        session = event.session

        member_email = user.email if user is not None else event.email
        device_summary = ""
        if session is not None:
            device_summary = " · ".join(part for part in (session.device_type, session.browser, session.os) if part)

        return {
            "id": str(exclusion.id),
            "name": f"{member_email} — {event.event_code}",
            "workspace_id": str(exclusion.workspace_id),
            "event_id": str(event.id),
            "member_email": member_email,
            "event_code": event.event_code,
            "success": event.success,
            "occurred_at": str(event.created_at),
            "device_summary": device_summary,
        }

    def restore(self, entity_id: str) -> None:
        from infrastructure.persistence.users.models import WorkspaceLoginActivityExclusion

        deleted, _ = WorkspaceLoginActivityExclusion.objects.filter(id=entity_id).delete()
        logger.info("login_activity_exclusion_restored exclusion_id=%s rows_deleted=%s", entity_id, deleted)

    def hard_delete(self, entity_id: str) -> None:
        from infrastructure.persistence.users.models import WorkspaceLoginActivityExclusion

        # Purges ONLY the exclusion marker — the AuthAuditEvent is
        # append-only and always survives.
        WorkspaceLoginActivityExclusion.objects.filter(id=entity_id).delete()

    def entity_type(self) -> str:
        return "login_activity"
