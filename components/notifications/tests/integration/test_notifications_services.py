import pytest

from components.notifications.infrastructure.adapters.notification_service import workspace_recipient_builder
from infrastructure.persistence.team.models import TeamMembership, Team


pytestmark = pytest.mark.django_db


def test_workspace_recipient_builder_includes_team_members(workspace_factory, user_factory, plan):
    workspace = workspace_factory()
    member = user_factory()
    team = Team.objects.create(workspace_id=workspace.id, title="Team A", created_by=workspace.workspace_owner, plan=plan)
    TeamMembership.objects.create(team=team, user=member)

    recipients = workspace_recipient_builder(
        workspace,
        include_owner=False,
        include_followers=False,
        include_donors=False,
    ).build()

    assert member in recipients
