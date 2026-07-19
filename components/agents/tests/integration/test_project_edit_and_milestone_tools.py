"""DB-backed tests for project_agent edit + milestone tools (PR-C1).

The audit found project_agent had ``create_project`` and ``list_projects``
but no generic update + no milestone update/delete. The dead code
references (``project.name``, ``project.notes``, broken Risk model)
were also surfaced — see the agent module's REMOVED comments for the
specifics.

These tests exercise the new tools against the real ORM. Cross-workspace
scoping is enforced via the same ``_resolve_project_for_update`` helper
as the task tools.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from components.agents.infrastructure.adapters.langchain.tools import (
    project_agent as project_tools,
)


def _make_agent(workspace_id, user=None):
    agent = MagicMock()
    agent.workspace_id = workspace_id
    agent.user_id = user.id if user else None
    agent.config = {}
    return agent


@pytest.fixture
def project_setup(workspace_factory, user_factory, team_factory):
    """A workspace + team + project ready to edit."""
    from infrastructure.persistence.project.models import Project

    user = user_factory()
    workspace = workspace_factory(owner=user)
    team = team_factory(workspace=workspace, created_by=user)
    project = Project.objects.create(
        workspace=workspace,
        team=team,
        title="Original project",
        description="Original description",
        created_by=user,
    )
    return {
        "user": user,
        "workspace": workspace,
        "team": team,
        "project": project,
        "agent": _make_agent(workspace.id, user),
    }


# ── update_project ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateProject:
    def test_renames_project(self, project_setup):
        result = project_tools.update_project(
            project_setup["agent"],
            {"project_id": str(project_setup["project"].id), "title": "New name"},
        )
        project_setup["project"].refresh_from_db()
        assert project_setup["project"].title == "New name"
        assert "Updated project" in result

    def test_updates_description(self, project_setup):
        project_tools.update_project(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "description": "Brand new description",
            },
        )
        project_setup["project"].refresh_from_db()
        assert project_setup["project"].description == "Brand new description"

    def test_updates_dates(self, project_setup):
        project_tools.update_project(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "start_date": "2026-06-01",
                "end_date": "2026-09-30",
            },
        )
        project_setup["project"].refresh_from_db()
        assert project_setup["project"].start_date == date(2026, 6, 1)
        assert project_setup["project"].end_date == date(2026, 9, 30)

    def test_clears_dates_with_null(self, project_setup):
        project_setup["project"].start_date = date(2026, 6, 1)
        project_setup["project"].save(update_fields=["start_date"])
        project_tools.update_project(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "start_date": None,
            },
        )
        project_setup["project"].refresh_from_db()
        assert project_setup["project"].start_date is None

    def test_rejects_empty_title(self, project_setup):
        result = project_tools.update_project(
            project_setup["agent"],
            {"project_id": str(project_setup["project"].id), "title": "   "},
        )
        assert "title cannot be empty" in result
        project_setup["project"].refresh_from_db()
        assert project_setup["project"].title == "Original project"

    def test_rejects_unparseable_date(self, project_setup):
        result = project_tools.update_project(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "start_date": "next Friday",
            },
        )
        assert "Could not parse" in result

    def test_rejects_no_fields(self, project_setup):
        result = project_tools.update_project(
            project_setup["agent"],
            {"project_id": str(project_setup["project"].id)},
        )
        assert "No fields provided" in result

    def test_rejects_unknown_project(self, project_setup):
        result = project_tools.update_project(
            project_setup["agent"],
            {"project_id": "00000000-0000-0000-0000-000000000000", "title": "x"},
        )
        assert "not found" in result

    def test_rejects_cross_workspace(self, workspace_factory, user_factory, team_factory):
        from infrastructure.persistence.project.models import Project

        u = user_factory()
        ws_a = workspace_factory(owner=u)
        ws_b = workspace_factory(owner=u)
        team_b = team_factory(workspace=ws_b, created_by=u)
        project_in_b = Project.objects.create(
            workspace=ws_b, team=team_b, title="Other ws project", created_by=u
        )
        result = project_tools.update_project(
            _make_agent(ws_a.id, u),
            {"project_id": str(project_in_b.id), "title": "Hijacked"},
        )
        assert "not found" in result
        project_in_b.refresh_from_db()
        assert project_in_b.title == "Other ws project"

    def test_rejects_unknown_lead_user(self, project_setup):
        result = project_tools.update_project(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "lead_user_id": "00000000-0000-0000-0000-000000000000",
            },
        )
        assert "not found" in result.lower()

    def test_assigns_lead(self, project_setup, user_factory):
        new_lead = user_factory()
        project_tools.update_project(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "lead_user_id": str(new_lead.id),
            },
        )
        project_setup["project"].refresh_from_db()
        assert project_setup["project"].lead_id == new_lead.id


# ── update_project_status (compat shim) ────────────────────────────────


@pytest.mark.django_db
class TestUpdateProjectStatusShim:
    def test_delegates_to_update_project(self, project_setup):
        """The shim must produce the same result as update_project for status changes."""
        result = project_tools.update_project_status(
            project_setup["agent"],
            {"project_id": str(project_setup["project"].id), "status": "BA"},
        )
        project_setup["project"].refresh_from_db()
        assert project_setup["project"].status == "BA"
        # Wording matches update_project's success format.
        assert "Updated project" in result


# ── update_project_milestone ──────────────────────────────────────────


@pytest.mark.django_db
class TestUpdateProjectMilestone:
    def _attach_milestone(self, project, **kwargs):
        from infrastructure.persistence.project.models import ProjectMilestone

        defaults = {
            "name": "Original milestone",
            "description": "Original",
            "target_date": date(2026, 6, 1),
        }
        defaults.update(kwargs)
        m = ProjectMilestone.objects.create(**defaults)
        project.milestones.add(m)
        return m

    def test_renames_milestone(self, project_setup):
        m = self._attach_milestone(project_setup["project"])
        result = project_tools.update_project_milestone(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "milestone_id": str(m.id),
                "name": "Renamed",
            },
        )
        m.refresh_from_db()
        assert m.name == "Renamed"
        assert "Renamed" in result

    def test_updates_target_date(self, project_setup):
        m = self._attach_milestone(project_setup["project"])
        project_tools.update_project_milestone(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "milestone_id": str(m.id),
                "target_date": "2027-01-15",
            },
        )
        m.refresh_from_db()
        assert m.target_date == date(2027, 1, 15)

    def test_rejects_milestone_not_on_project(self, project_setup):
        from infrastructure.persistence.project.models import ProjectMilestone

        # Milestone exists but isn't attached to the project.
        m = ProjectMilestone.objects.create(
            name="Loose milestone",
            description="Not attached",
            target_date=date(2026, 6, 1),
        )
        result = project_tools.update_project_milestone(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "milestone_id": str(m.id),
                "name": "Try to rename",
            },
        )
        assert "not attached" in result.lower()

    def test_rejects_blank_name(self, project_setup):
        m = self._attach_milestone(project_setup["project"])
        result = project_tools.update_project_milestone(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "milestone_id": str(m.id),
                "name": "  ",
            },
        )
        assert "name cannot be empty" in result

    def test_rejects_clearing_target_date(self, project_setup):
        m = self._attach_milestone(project_setup["project"])
        result = project_tools.update_project_milestone(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "milestone_id": str(m.id),
                "target_date": None,
            },
        )
        assert "cannot be cleared" in result


# ── delete_project_milestone ──────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteProjectMilestone:
    def _attach_milestone(self, project):
        from infrastructure.persistence.project.models import ProjectMilestone

        m = ProjectMilestone.objects.create(
            name="Doomed milestone",
            description="x",
            target_date=date(2026, 6, 1),
        )
        project.milestones.add(m)
        return m

    def test_removes_milestone_from_project(self, project_setup):
        m = self._attach_milestone(project_setup["project"])
        m_id = m.id
        result = project_tools.delete_project_milestone(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "milestone_id": str(m_id),
            },
        )
        assert "Deleted milestone" in result
        # Detached from the project.
        assert not project_setup["project"].milestones.filter(id=m_id).exists()

    def test_keeps_milestone_alive_when_attached_to_other_project(
        self, project_setup, user_factory, team_factory, workspace_factory
    ):
        from infrastructure.persistence.project.models import (
            Project,
            ProjectMilestone,
        )

        # A second project (in same workspace for simplicity).
        other_project = Project.objects.create(
            workspace=project_setup["workspace"],
            team=project_setup["team"],
            title="Other project",
            created_by=project_setup["user"],
        )
        m = self._attach_milestone(project_setup["project"])
        other_project.milestones.add(m)
        m_id = m.id

        project_tools.delete_project_milestone(
            project_setup["agent"],
            {
                "project_id": str(project_setup["project"].id),
                "milestone_id": str(m_id),
            },
        )
        # Detached from the deleted-source project.
        assert not project_setup["project"].milestones.filter(id=m_id).exists()
        # Still attached to the OTHER project AND still in the table.
        assert other_project.milestones.filter(id=m_id).exists()
        assert ProjectMilestone.objects.filter(id=m_id).exists()
