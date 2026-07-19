"""Workspace AI teammate sync adapter.

Coordinates AI teammate lifecycle when workspace AI settings change.
Calls the agents context's **published facade** — no ports, no adapters,
just a direct facade import (the approved cross-context pattern).
"""
from __future__ import annotations


class WorkspaceAiTeammateSyncAdapter:

    def sync(self, *, workspace) -> None:
        from components.agents.application.facades.ai_teammate_facade import (
            disable_teammate,
            enable_teammate,
            get_teammate_profile,
        )

        profile = get_teammate_profile(str(workspace.id))
        status_changed = False

        if workspace.ai_teammate_enabled:
            profile, ai_user = enable_teammate(workspace)

            if not profile.is_enabled or getattr(profile, "status", None) == "disabled":
                profile.is_enabled = True
                profile.status = "active"
                profile.save(update_fields=["is_enabled", "status", "updated_at"])
                status_changed = True
        else:
            if profile and profile.is_enabled:
                disable_teammate(workspace)
                profile.refresh_from_db()
                status_changed = True

        if status_changed and profile:
            self._notify_toggle(workspace=workspace, profile=profile)

    def _notify_toggle(self, *, workspace, profile) -> None:
        actor = getattr(profile, "user", None)
        if not actor:
            return

        from components.notifications.infrastructure.adapters.notification_service import (
            NotificationDispatcher,
            workspace_recipient_builder,
        )
        from infrastructure.persistence.notifications.models import (
            AINotificationPreference,
            Notification,
        )

        recipients = workspace_recipient_builder(
            workspace, include_donors=False
        ).build()
        if not recipients:
            return

        NotificationDispatcher().dispatch(
            actor=actor,
            workspace=workspace,
            verb=(
                "enabled the Orchestrator agent"
                if workspace.ai_teammate_enabled
                else "disabled the Orchestrator agent"
            ),
            notification_type=Notification.NotificationType.AI_EVENT,
            recipients=recipients,
            metadata={
                "event": "workspaces.ai_teammate_toggle",
                "is_enabled": workspace.ai_teammate_enabled,
            },
            target=workspace,
            ai_channel=AINotificationPreference.CHANNEL_TEAMMATE_STATUS,
        )
