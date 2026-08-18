"""Model invariants for ``WorkflowStatus`` + ``BoardView`` (ADR 0030 P1).

Each constraint the ADR names gets a test: the category axis is a closed
TextChoices, a status name exists at most once per (team, workspace), and the
``BoardView.filter`` vocabulary is CLOSED — an unknown key is rejected at the
model boundary (clean AND save), because "not a query language" is a design
decision, not a convention.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from infrastructure.persistence.project.models import (
    BOARD_VIEW_FILTER_KEYS,
    BoardView,
    WorkflowStatus,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _team(workspace_factory, team_factory):
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return workspace, team


class TestWorkflowStatusConstraints:
    def test_category_choices_reject_an_unknown_value(self, workspace_factory, team_factory):
        workspace, team = _team(workspace_factory, team_factory)
        status = WorkflowStatus(workspace=workspace, team=team, name="Todo", order=2, category="bogus")

        with pytest.raises(ValidationError) as excinfo:
            status.full_clean()

        assert "category" in excinfo.value.message_dict

    def test_category_choices_match_the_domain_vocabulary(self):
        """The model's axis and the domain vocabulary can never disagree —
        the TextChoices values ARE the vocabulary constants."""
        from components.project.domain.workflow_status_vocabulary import CATEGORIES

        assert tuple(WorkflowStatus.Category.values) == CATEGORIES

    def test_status_name_is_unique_per_team_and_workspace(self, workspace_factory, team_factory):
        workspace, team = _team(workspace_factory, team_factory)
        WorkflowStatus.objects.create(workspace=workspace, team=team, name="Todo", order=2, category="unstarted")

        with pytest.raises(IntegrityError), transaction.atomic():
            WorkflowStatus.objects.create(workspace=workspace, team=team, name="Todo", order=9, category="started")

    def test_same_name_is_allowed_on_a_different_team(self, workspace_factory, team_factory):
        workspace_a, team_a = _team(workspace_factory, team_factory)
        workspace_b, team_b = _team(workspace_factory, team_factory)
        WorkflowStatus.objects.create(workspace=workspace_a, team=team_a, name="Todo", order=2, category="unstarted")

        # One vocabulary PER TEAM — another team's "Todo" is its own row.
        WorkflowStatus.objects.create(workspace=workspace_b, team=team_b, name="Todo", order=2, category="unstarted")

        assert WorkflowStatus.objects.filter(name="Todo").count() == 2


class TestBoardViewFilterVocabulary:
    def test_save_rejects_an_unknown_filter_key(self, workspace_factory, team_factory):
        workspace, team = _team(workspace_factory, team_factory)
        view = BoardView(workspace=workspace, team=team, name="Rogue", slug="rogue", filter={"jql": "everything"})

        with pytest.raises(ValidationError) as excinfo:
            view.save()

        assert "jql" in str(excinfo.value)
        assert not BoardView.objects.filter(slug="rogue").exists()

    def test_clean_rejects_an_unknown_filter_key(self, workspace_factory, team_factory):
        workspace, team = _team(workspace_factory, team_factory)
        view = BoardView(workspace=workspace, team=team, name="Rogue", slug="rogue", filter={"severity": "high"})

        with pytest.raises(ValidationError):
            view.clean()

    def test_save_rejects_a_non_object_filter(self, workspace_factory, team_factory):
        workspace, team = _team(workspace_factory, team_factory)
        view = BoardView(workspace=workspace, team=team, name="Rogue", slug="rogue", filter=["project"])

        with pytest.raises(ValidationError):
            view.save()

    def test_every_closed_vocabulary_key_is_accepted(self, workspace_factory, team_factory):
        workspace, team = _team(workspace_factory, team_factory)
        view = BoardView.objects.create(
            workspace=workspace,
            team=team,
            name="Everything",
            slug="everything",
            filter=dict.fromkeys(BOARD_VIEW_FILTER_KEYS, "x"),
        )

        assert set(view.filter) == BOARD_VIEW_FILTER_KEYS

    def test_the_vocabulary_is_exactly_the_adr_set(self):
        """Pin the closed set — extending it must edit this test, i.e. be a
        deliberate reviewed change (ADR 0030: "no query language")."""
        assert {
            "project",
            "source_type",
            "source_type_prefix",
            "category",
            "min_severity",
            "assignee",
            "tag",
        } == BOARD_VIEW_FILTER_KEYS

    def test_slug_is_unique_per_team_and_workspace(self, workspace_factory, team_factory):
        workspace, team = _team(workspace_factory, team_factory)
        BoardView.objects.create(workspace=workspace, team=team, name="Board", slug="board")

        with pytest.raises(IntegrityError), transaction.atomic():
            BoardView.objects.create(workspace=workspace, team=team, name="Board 2", slug="board")
