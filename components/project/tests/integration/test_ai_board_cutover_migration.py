"""Integration tests for the P3 AI-board cutover (project migration 0009).

Exercises ``cutover_ai_board`` / ``reverse_ai_board_cutover`` directly against
real models (the established migration-test pattern — see the 0008 tests).
Pins, forward:

* the ADR 0030 P3 re-point table (Suggested→Todo, Under Review/Triage/
  Optimize→In Progress, Accepted→Complete, Dismissed→Canceled);
* every moved card leaves with ``team``/``project``/``column`` consistent and
  ``workflow_status`` mirroring the destination lane;
* the prior placement is recorded per card (``metadata.board_cutover_p3``);
* Triage/Optimize cards get the ``metadata.triage`` chip — ONLY where no
  triage state exists (existing triage metadata is never clobbered);
* retired lanes are soft-deleted once empty; the canonical lanes exist on the
  AI Findings project board; the Intake/Acting system views are seeded;
* the migration is re-runnable (second run is a no-op).

Reverse:

* recorded cards return to exactly their recorded lane (soft-deleted lanes
  revived), migration-stamped chips removed, the record key popped;
* unrecorded post-cutover cards re-point by the inverse rule (Todo→Suggested,
  In Progress→Triage/Optimize by chip agent, Complete→Accepted,
  Canceled→Dismissed);
* the Intake/Acting views are removed.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps as django_apps

from infrastructure.persistence.project.models import (
    BoardView,
    Column,
    Project,
    Task,
    WorkflowStatus,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_migration = importlib.import_module(
    "infrastructure.persistence.project.migrations.0009_ai_board_cutover_to_canonical_lanes"
)
cutover = _migration.cutover_ai_board
reverse_cutover = _migration.reverse_ai_board_cutover


class _SchemaEditorStub:
    """The migration only reads ``schema_editor.connection.alias``."""

    class connection:
        alias = "default"


def _run_forward():
    cutover(django_apps, _SchemaEditorStub())


def _run_reverse():
    reverse_cutover(django_apps, _SchemaEditorStub())


def _old_world(workspace_factory, team_factory):
    """The pre-P3 two-board shape: 4 AI project lanes + lazy team lanes."""
    workspace = workspace_factory()
    owner = workspace.workspace_owner
    team = team_factory(workspace=workspace, created_by=owner, members=[owner], kind="ai_agents")
    project = Project.objects.create(workspace=workspace, team=team, title="AI Findings", created_by=owner)
    lanes = {}
    for title, order in (("Suggested", 0), ("Under Review", 1), ("Accepted", 2), ("Dismissed", 3)):
        lanes[title] = Column.objects.create(
            team=team, workspace=workspace, project=project, title=title, order=order, created_by=owner
        )
    for title, order in (("Triage", 1), ("Optimize", 2)):
        lanes[title] = Column.objects.create(
            team=team, workspace=workspace, project=None, title=title, order=order, created_by=owner
        )
    return workspace, owner, team, project, lanes


def _card(workspace, owner, team, project, column, *, source_type="ai.log_watch", metadata=None, title="Card"):
    return Task.objects.create(
        team=team,
        workspace=workspace,
        project=project,
        column=column,
        created_by=owner,
        title=title,
        source_type=source_type,
        metadata=metadata if metadata is not None else {"triage": {"status": "pending"}, "payload": {}},
    )


def _canonical(project, title):
    return Column.objects.get(project=project, title=title, is_deleted=False)


class TestForwardCutover:
    def test_repoints_cards_per_the_p3_table_with_consistent_fks(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        expectations = {
            "Suggested": "Todo",
            "Under Review": "In Progress",
            "Triage": "In Progress",
            "Optimize": "In Progress",
            "Accepted": "Complete",
            "Dismissed": "Canceled",
        }
        cards = {
            title: _card(workspace, owner, team, project, lanes[title], title=f"card-{title}") for title in expectations
        }

        _run_forward()

        for old_title, new_title in expectations.items():
            card = cards[old_title]
            card.refresh_from_db()
            assert card.column.title == new_title, old_title
            # One surface: every card lands on the AI Findings project board
            # with the three FKs consistent.
            assert card.project_id == project.id
            assert card.column.project_id == project.id
            assert card.team_id == card.column.team_id == team.id
            # The status axis mirrors the lane.
            assert card.workflow_status_id == card.column.workflow_status_id
            assert card.workflow_status.name == new_title
            # The prior placement is recorded (this is what makes it reversible).
            record = card.metadata["board_cutover_p3"]
            assert record["prior_column_id"] == lanes[old_title].id
            assert record["prior_column_title"] == old_title

    def test_triage_and_optimize_cards_get_the_chip_without_clobbering(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        fresh_triage = _card(workspace, owner, team, project, lanes["Triage"], metadata={"payload": {}})
        fresh_optimize = _card(workspace, owner, team, project, lanes["Optimize"], metadata={"payload": {}})
        already_stamped = _card(
            workspace,
            owner,
            team,
            project,
            lanes["Triage"],
            metadata={"triage": {"status": "triaged", "agent": "triage_agent", "suggested": True}, "payload": {}},
        )
        human_task = _card(workspace, owner, team, project, lanes["Triage"], source_type="", metadata={})

        _run_forward()

        fresh_triage.refresh_from_db()
        assert fresh_triage.metadata["triage"]["status"] == "triaged"
        assert fresh_triage.metadata["triage"]["agent"] == "triage_agent"
        assert fresh_triage.metadata["board_cutover_p3"]["stamped_triage"] is True

        fresh_optimize.refresh_from_db()
        assert fresh_optimize.metadata["triage"]["agent"] == "optimization_agent"

        already_stamped.refresh_from_db()
        assert already_stamped.metadata["triage"]["suggested"] is True  # untouched
        assert "stamped_triage" not in already_stamped.metadata["board_cutover_p3"]

        human_task.refresh_from_db()
        assert "triage" not in human_task.metadata  # no fake AI state on a human card
        assert human_task.column.title == "In Progress"  # still re-pointed

    def test_retired_lanes_are_soft_deleted_once_empty_and_views_seeded(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        _card(workspace, owner, team, project, lanes["Suggested"])

        _run_forward()

        for title, lane in lanes.items():
            lane.refresh_from_db()
            assert lane.is_deleted is True, title

        views = {v.slug: v for v in BoardView.objects.filter(team=team, workspace=workspace, is_system=True)}
        assert views["intake"].filter == {"source_type_prefix": "ai.", "category": "unstarted"}
        assert views["acting"].filter == {"source_type_prefix": "ai.", "category": "started"}

    def test_rerun_is_a_noop(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        card = _card(workspace, owner, team, project, lanes["Suggested"])

        _run_forward()
        card.refresh_from_db()
        first_meta = card.metadata
        first_column_id = card.column_id
        columns_before = Column.objects.filter(team=team).count()
        views_before = BoardView.objects.filter(team=team).count()

        _run_forward()

        card.refresh_from_db()
        assert card.column_id == first_column_id
        assert card.metadata == first_meta
        assert Column.objects.filter(team=team).count() == columns_before
        assert BoardView.objects.filter(team=team).count() == views_before

    def test_team_without_kind_but_with_ai_findings_project_is_covered(self, workspace_factory, team_factory):
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])  # default kind
        project = Project.objects.create(workspace=workspace, team=team, title="AI Findings", created_by=owner)
        suggested = Column.objects.create(
            team=team, workspace=workspace, project=project, title="Suggested", order=0, created_by=owner
        )
        card = _card(workspace, owner, team, project, suggested)

        _run_forward()

        card.refresh_from_db()
        assert card.column.title == "Todo"

    def test_non_agents_team_lanes_are_untouched(self, workspace_factory, team_factory):
        """A human team's hand-made "Triage" column is not an AI surface."""
        workspace = workspace_factory()
        owner = workspace.workspace_owner
        team = team_factory(workspace=workspace, created_by=owner, members=[owner])  # no AI project, not ai_agents
        triage = Column.objects.create(
            team=team, workspace=workspace, project=None, title="Triage", order=0, created_by=owner
        )
        card = _card(workspace, owner, team, None, triage, source_type="")

        _run_forward()

        card.refresh_from_db()
        triage.refresh_from_db()
        assert card.column_id == triage.id
        assert triage.is_deleted is False
        assert not BoardView.objects.filter(team=team, slug="intake").exists()


class TestReverseCutover:
    def test_recorded_cards_return_to_their_exact_lanes(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        suggested_card = _card(workspace, owner, team, project, lanes["Suggested"])
        triage_card = _card(workspace, owner, team, project, lanes["Triage"], metadata={"payload": {}})

        _run_forward()
        _run_reverse()

        suggested_card.refresh_from_db()
        assert suggested_card.column_id == lanes["Suggested"].id
        assert "board_cutover_p3" not in suggested_card.metadata
        lanes["Suggested"].refresh_from_db()
        assert lanes["Suggested"].is_deleted is False  # revived for the restore

        triage_card.refresh_from_db()
        assert triage_card.column_id == lanes["Triage"].id
        # The migration-stamped chip is removed; the pre-P3 F1 shape (project
        # kept, team-board column) is faithfully restored.
        assert "triage" not in triage_card.metadata
        assert triage_card.project_id == project.id

    def test_reverse_preserves_specialist_stamped_chips(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        stamped = _card(
            workspace,
            owner,
            team,
            project,
            lanes["Triage"],
            metadata={"triage": {"status": "triaged", "agent": "triage_agent", "suggested": True}, "payload": {}},
        )

        _run_forward()
        _run_reverse()

        stamped.refresh_from_db()
        assert stamped.metadata["triage"]["status"] == "triaged"  # not ours to remove

    def test_unrecorded_post_cutover_cards_follow_the_inverse_rule(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        _card(workspace, owner, team, project, lanes["Suggested"])  # forces the full forward pass

        _run_forward()

        todo = _canonical(project, "Todo")
        in_progress = _canonical(project, "In Progress")
        complete = _canonical(project, "Complete")
        born_after = _card(workspace, owner, team, project, todo, title="born-after")
        acting_opt = _card(
            workspace,
            owner,
            team,
            project,
            in_progress,
            title="acting-opt",
            metadata={"triage": {"status": "triaged", "agent": "optimization_agent"}, "payload": {}},
        )
        accepted_after = _card(workspace, owner, team, project, complete, title="accepted-after")

        _run_reverse()

        born_after.refresh_from_db()
        assert born_after.column.title == "Suggested"
        acting_opt.refresh_from_db()
        assert acting_opt.column.title == "Optimize"
        assert acting_opt.column.project_id is None  # the pre-P3 team-board lane
        accepted_after.refresh_from_db()
        assert accepted_after.column.title == "Accepted"

    def test_reverse_removes_the_system_views(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        _card(workspace, owner, team, project, lanes["Suggested"])

        _run_forward()
        assert BoardView.objects.filter(team=team, slug__in=("intake", "acting")).count() == 2

        _run_reverse()
        assert not BoardView.objects.filter(team=team, slug__in=("intake", "acting")).exists()


class TestCanonicalLaneSeed:
    def test_canonical_lanes_carry_their_status(self, workspace_factory, team_factory):
        workspace, owner, team, project, lanes = _old_world(workspace_factory, team_factory)
        _card(workspace, owner, team, project, lanes["Suggested"])

        _run_forward()

        for name in ("Backlog", "Todo", "In Progress", "Testing", "Complete", "Canceled"):
            column = _canonical(project, name)
            status = WorkflowStatus.objects.get(team=team, workspace=workspace, name=name)
            assert column.workflow_status_id == status.id
