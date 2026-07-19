"""ORM adapter implementing LoginActivityExclusionPort.

``get_or_create`` rides the model's unique(workspace, event) constraint
so concurrent hide requests converge on one row.
"""

from __future__ import annotations

from uuid import UUID

from components.identity.application.ports.login_activity_exclusion_port import LoginActivityExclusionPort


class OrmLoginActivityExclusionRepository(LoginActivityExclusionPort):
    """Concrete exclusion store backed by the Django ORM."""

    def get_or_create(self, *, workspace_id: UUID, event_id: int, hidden_by: UUID) -> tuple[UUID, bool]:
        from infrastructure.persistence.users.models import WorkspaceLoginActivityExclusion

        exclusion, created = WorkspaceLoginActivityExclusion.objects.get_or_create(
            workspace_id=workspace_id,
            event_id=event_id,
            defaults={"hidden_by_id": hidden_by},
        )
        return exclusion.id, created
