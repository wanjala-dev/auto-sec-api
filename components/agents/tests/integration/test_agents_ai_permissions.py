"""Tests for AI executor grants and workspace enablement."""


import pytest

from components.agents.api.permissions import ai_can, ensure_agents_team, ensure_ai_identity
from infrastructure.persistence.ai.models import AIPermissionGrant
from infrastructure.persistence.team.models import Team


@pytest.mark.django_db
def test_enable_ai_creates_identity_grant_and_team(workspace_factory):
    workspace = workspace_factory(ai_teammate_enabled=True)

    profile, ai_user = ensure_ai_identity(workspace)
    team = ensure_agents_team(workspace, ai_user)

    assert profile.user == ai_user
    assert team.members.filter(id=ai_user.id).exists()
    assert team.kind == Team.Kind.AI_AGENTS
    assert AIPermissionGrant.objects.filter(
        workspace=workspace,
        principal=ai_user,
        role=AIPermissionGrant.ROLE_AI_EXECUTOR,
        status=AIPermissionGrant.STATUS_ACTIVE,
        scope_type=AIPermissionGrant.SCOPE_WORKSPACE,
    ).exists()
    grant = AIPermissionGrant.objects.get(
        workspace=workspace,
        principal=ai_user,
        role=AIPermissionGrant.ROLE_AI_EXECUTOR,
        scope_type=AIPermissionGrant.SCOPE_WORKSPACE,
    )
    assert grant.actions
    assert ai_can(str(workspace.id), str(ai_user.id), action="task:write") is True


# NOTE (autosec fork): test_ai_grant_allows_task_and_budget_permissions was removed
# with the nonprofit ``budget_agent`` tool it asserted against. The AI-executor grant
# + ``ai_can`` surface it exercised stays covered by the two tests here.


@pytest.mark.django_db
def test_ai_can_respects_department_scope(workspace_factory, user_factory, team_factory):
    workspace = workspace_factory()
    user = user_factory()
    department = team_factory(workspace=workspace, kind=Team.Kind.DEPARTMENT)
    other_department = team_factory(workspace=workspace, kind=Team.Kind.DEPARTMENT)

    AIPermissionGrant.objects.create(
        workspace=workspace,
        principal=user,
        role=AIPermissionGrant.ROLE_AI_EXECUTOR,
        status=AIPermissionGrant.STATUS_ACTIVE,
        scope_type=AIPermissionGrant.SCOPE_DEPARTMENT,
        scope_id=str(department.id),
        actions=["task:write"],
    )

    assert ai_can(
        str(workspace.id),
        str(user.id),
        action="task:write",
        scope_type=AIPermissionGrant.SCOPE_DEPARTMENT,
        scope_id=str(department.id),
    )
    assert not ai_can(
        str(workspace.id),
        str(user.id),
        action="task:write",
        scope_type=AIPermissionGrant.SCOPE_DEPARTMENT,
        scope_id=str(other_department.id),
    )
