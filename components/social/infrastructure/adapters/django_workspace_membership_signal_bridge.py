"""Signal bridge: auto-follow on private-workspace membership.

Listens to ``WorkspaceMembership.post_save``. When a new ACTIVE membership
lands in a PERSONAL workspace, we wire mutual follows between the new
member and every existing member so their feed has content on day one.

Teamspaces are intentionally NOT auto-followed — the empty-feed
experience there is handled by a "suggested members" rail on the
frontend.
"""

from __future__ import annotations

import logging

from django.db.models.signals import post_save

logger = logging.getLogger(__name__)


def _handle_membership_save(sender, instance, created, **kwargs):
    # Only react to ACTIVE memberships, never drafts/invites/suspended.
    if instance.status != instance.Status.ACTIVE:
        return
    workspace = getattr(instance, "workspace", None)
    if workspace is None or workspace.workspace_type != workspace.PERSONAL:
        return

    # Defer provider lookup to call-time to avoid circular imports during
    # Django's app-loading phase.
    from components.social.application.providers.feed_provider import FeedProvider

    try:
        FeedProvider.auto_follow_use_case().execute(
            new_member_id=instance.user_id,
            workspace_id=instance.workspace_id,
        )
    except Exception:
        logger.exception(
            "auto_follow_on_membership_save failed membership_id=%s user_id=%s workspace_id=%s",
            instance.pk,
            instance.user_id,
            instance.workspace_id,
        )


class DjangoWorkspaceMembershipSignalBridge:
    @staticmethod
    def register() -> None:
        from infrastructure.persistence.workspaces.models import WorkspaceMembership

        post_save.connect(
            _handle_membership_save,
            sender=WorkspaceMembership,
            dispatch_uid="social:auto_follow_on_private_workspace_join",
        )
