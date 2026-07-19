"""Tests for deep project creation helpers."""
from __future__ import annotations

import pytest

from components.agents.infrastructure.adapters.langchain.deep.project import run_project_creation
from components.agents.domain.value_objects.plan_schemas import PlanSpec, TaskSpec, BudgetLine
from infrastructure.persistence.budget.transactions.models import Transaction
from infrastructure.persistence.budget.categories.models import Category
from infrastructure.persistence.project.models import Project, Task
from infrastructure.persistence.team.models import Team


@pytest.mark.django_db
def test_run_project_creation_uses_budget_lines(workspace_factory, user_factory, team_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    team_factory(workspace=workspace, members=[user], kind=Team.Kind.DEPARTMENT)

    category = Category.objects.create(
        workspace=workspace,
        user=user,
        name="Operations",
        slug="operations",
    )
    plan = PlanSpec(
        plan_id="plan-1",
        goal="Plan a well project",
        tasks=[TaskSpec(title="Site survey")],
        budget_lines=[
            BudgetLine(
                label="Survey cost",
                amount=123.45,
                metadata={"category_id": str(category.id), "category_name": category.name},
            )
        ],
    )

    result = run_project_creation(
        project_title="Digging a well",
        workspace_id=str(workspace.id),
        user_id=str(user.id),
        plan=plan,
    )

    project = Project.objects.get(id=result["project_id"])
    transactions = Transaction.objects.filter(project=project, transaction_type="expense")
    tasks = Task.objects.filter(project=project)

    assert transactions.count() == 1
    txn = transactions.first()
    assert txn.notes == "Survey cost"
    assert str(txn.category_id) == str(category.id)
    assert tasks.count() == 1
    assert tasks.first().assigned_to.filter(id=user.id).exists()


@pytest.mark.django_db
def test_run_project_creation_creates_agents_team_when_missing(workspace_factory, user_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user, ai_teammate_enabled=False)

    plan = PlanSpec(
        plan_id="plan-2",
        goal="Plan without existing teams",
        tasks=[TaskSpec(title="Kickoff")],
        budget_lines=[],
    )

    run_project_creation(
        project_title="New project",
        workspace_id=str(workspace.id),
        user_id=str(user.id),
        plan=plan,
    )

    agents_team = Team.objects.get(workspace=workspace, title__iexact="Agents")
    assert agents_team.kind == Team.Kind.AI_AGENTS
    assert agents_team.members.filter(id=user.id).exists()


@pytest.mark.django_db
def test_run_project_creation_requires_permission(workspace_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner, ai_teammate_enabled=False)
    requester = user_factory()

    plan = PlanSpec(
        plan_id="plan-3",
        goal="Plan without access",
        tasks=[TaskSpec(title="Kickoff")],
        budget_lines=[],
    )

    with pytest.raises(PermissionError):
        run_project_creation(
            project_title="Unauthorized project",
            workspace_id=str(workspace.id),
            user_id=str(requester.id),
            plan=plan,
        )


@pytest.mark.django_db
def test_run_project_creation_builds_tasks_when_plan_empty(workspace_factory, user_factory, team_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    team_factory(workspace=workspace, members=[user], kind=Team.Kind.DEPARTMENT)

    category = Category.objects.create(
        workspace=workspace,
        user=user,
        name="General",
        slug="general",
    )
    plan = PlanSpec(
        plan_id="plan-empty",
        goal="Plan without tasks",
        tasks=[],
        budget_lines=[
            BudgetLine(
                label="Initial estimate",
                amount=500.00,
                metadata={"category_id": str(category.id), "category_name": category.name},
            )
        ],
    )

    result = run_project_creation(
        project_title="Fallback tasks project",
        workspace_id=str(workspace.id),
        user_id=str(user.id),
        plan=plan,
    )

    project = Project.objects.get(id=result["project_id"])
    tasks = Task.objects.filter(project=project)
    assert tasks.count() > 0
    assert tasks.first().assigned_to.filter(id=user.id).exists()


@pytest.mark.django_db
def test_run_project_creation_creates_estimate_transactions(workspace_factory, user_factory, team_factory):
    user = user_factory()
    workspace = workspace_factory(owner=user)
    team_factory(workspace=workspace, members=[user], kind=Team.Kind.DEPARTMENT)

    category = Category.objects.create(
        workspace=workspace,
        user=user,
        name="Setup",
        slug="setup",
    )
    long_title = "Buying Tiny Homes for Homeless People Project with Extra Words"
    plan = PlanSpec(
        plan_id="plan-long-title",
        goal="Plan with long title",
        tasks=[TaskSpec(title="Kickoff")],
        budget_lines=[
            BudgetLine(
                label="Kickoff cost",
                amount=100.00,
                metadata={"category_id": str(category.id), "category_name": category.name},
            )
        ],
    )

    result = run_project_creation(
        project_title=long_title,
        workspace_id=str(workspace.id),
        user_id=str(user.id),
        plan=plan,
    )

    transactions = Transaction.objects.filter(project_id=result["project_id"])
    assert transactions.exists()
