import pytest

from infrastructure.persistence.project.models import Project, ProjectUpdate


pytestmark = pytest.mark.django_db


def test_project_update_children_and_parent(workspace_factory, user_factory, team_factory):
    workspace = workspace_factory()
    user = user_factory()
    team = team_factory(workspace=workspace, created_by=user)
    team.members.add(user)
    project = Project.objects.create(workspace=workspace, team=team, title="Build", created_by=user)
    parent_update = ProjectUpdate.objects.create(Update="Parent", workspace=workspace, Project=project, author=user)
    recipient_update = ProjectUpdate.objects.create(Update="Recipient", workspace=workspace, Project=project, author=user, parent=parent_update)

    assert parent_update.is_parent is True
    assert list(parent_update.recipients) == [recipient_update]
