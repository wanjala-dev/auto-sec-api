"""ORM-backed WorkspaceProfilePort — the sanctioned cross-context read.

Reads the handful of ``workspaces`` brand fields a newsletter draft lays
itself out with and returns them as a frozen ``WorkspaceProfile``. This is the
ONE place the content context is allowed to touch ``workspaces`` persistence
(architecture skill C3: cross-context reads live in an infra adapter behind a
port). Mirrors ``template_placeholder_resolver``'s ``workspace_name`` read,
generalised to the fields the newsletter composer needs.
"""

from __future__ import annotations

import logging
from uuid import UUID

from components.content.application.ports.workspace_profile_port import (
    WorkspaceProfilePort,
)
from components.content.domain.value_objects.workspace_profile import (
    WorkspaceProfile,
)

logger = logging.getLogger(__name__)


class OrmWorkspaceProfileAdapter(WorkspaceProfilePort):
    def get_profile(self, *, workspace_id: UUID) -> WorkspaceProfile:
        # Best-effort — a missing workspace or read error degrades to a blank
        # profile (the composer drops blocks it can't populate, the grounded
        # summary falls back to a generic org label, and the hero falls back
        # to a curated stock photo). A newsletter draft must never fail
        # because a brand field couldn't be resolved.
        try:
            from infrastructure.persistence.workspaces.models import Workspace

            workspace = (
                Workspace.objects.filter(pk=workspace_id)
                .only(
                    "workspace_name",
                    "contact_email",
                    "mission",
                    "cover_photo_url",
                    "photo_url",
                )
                .first()
            )
            if workspace is not None:
                return WorkspaceProfile(
                    name=workspace.workspace_name or "",
                    contact_email=workspace.contact_email or "",
                    mission=workspace.mission or "",
                    cover_photo_url=workspace.cover_photo_url or "",
                    photo_url=workspace.photo_url or "",
                )
        except Exception:
            logger.exception(
                "newsletter.workspace_profile_read_failed workspace_id=%s",
                workspace_id,
            )
        return WorkspaceProfile()
