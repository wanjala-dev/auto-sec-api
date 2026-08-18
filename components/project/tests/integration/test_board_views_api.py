"""Integration — the boards-as-views read API (ADR 0030 P2a).

Contract under test:

* ``GET /project/teams/<team_id>/views/`` — the team's ordered ``BoardView``
  rows (system views from the P1 backfill; user-saved views later).
* ``GET /project/views/<view_id>/board/`` — lanes from the team's
  ``WorkflowStatus`` rows (ordered, with category); lane membership is
  ``task.workflow_status`` restricted by the view's closed-vocabulary
  ``filter`` (project / source_type / min_severity / assignee / tag).
* ``GET /project/views/<view_id>/lanes/<status_id>/tasks/`` — one lane's
  load-more pager, same ordering/eager-loading as the board windows.
* Windowing parity with the column board: ``tasks_limit`` per lane,
  ``tasks_total`` / ``tasks_has_more``, identical clamping.
* Flag gating: ``feature.boards_as_views`` via ``RequiresFeatureFlag`` — the
  repo's established convention for flag-gated endpoints (flag off → 403
  "Feature not enabled.", never 404); today's column board is untouched
  either way.
* Isolation (tenancy invariant 8): another workspace's team/view/status id
  answers 404 exactly like a missing id — existence never leaks across the
  tenant boundary — and no response ever contains another workspace's rows.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from components.project.domain.workflow_status_vocabulary import CANONICAL_STATUSES
from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from components.workspace.application.ports.column_query_port import (
    DEFAULT_COLUMN_TASKS_LIMIT,
    MAX_COLUMN_TASKS_LIMIT,
)
from infrastructure.persistence.core.models import FeatureFlag, FeatureFlagRule
from infrastructure.persistence.project.models import (
    BoardView,
    Column,
    Project,
    Task,
    WorkflowStatus,
)
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = pytest.mark.django_db

FLAG_KEY = "feature.boards_as_views"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _board(workspace_factory, team_factory, user_factory):
    owner = user_factory()
    workspace = workspace_factory(owner=owner)
    team = team_factory(workspace=workspace, created_by=owner, members=[owner])
    return owner, workspace, team


def _seed_lanes(workspace, team, owner):
    """Create the canonical team-board columns; the P1 sync bridge lazily
    seeds the team's six ``WorkflowStatus`` rows and maps each column."""
    columns = {}
    for name, _category, order in CANONICAL_STATUSES:
        columns[name] = Column.objects.create(
            workspace=workspace, team=team, project=None, title=name, order=order, created_by=owner
        )
    statuses = {s.name: s for s in WorkflowStatus.objects.filter(team=team, workspace=workspace)}
    return columns, statuses


def _view(workspace, team, *, slug="board", name="Board", filter=None, order=0, is_system=True):
    return BoardView.objects.create(
        workspace=workspace,
        team=team,
        name=name,
        slug=slug,
        filter=filter or {},
        order=order,
        is_system=is_system,
    )


def _task(workspace, team, owner, column, *, title="Task", order=0, **kwargs):
    return Task.objects.create(
        workspace=workspace,
        team=team,
        column=column,
        title=title,
        order=order,
        created_by=owner,
        **kwargs,
    )


def _views_url(team):
    return reverse("project:team-board-views", kwargs={"team_id": team.id})


def _board_url(view):
    return reverse("project:view-board", kwargs={"view_id": view.id})


def _lane_url(view, status_row):
    return reverse("project:view-lane-tasks", kwargs={"view_id": view.id, "status_id": status_row.id})


def _lanes_by_name(response):
    return {lane["name"]: lane for lane in response.data["data"]["lanes"]}


@pytest.fixture
def board(workspace_factory, team_factory, user_factory):
    return _board(workspace_factory, team_factory, user_factory)


# ---------------------------------------------------------------------------
# Auth + flag gating
# ---------------------------------------------------------------------------


class TestAuthAndFlagGate:
    def test_unauthenticated_requests_are_401(self, api_client, board):
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        view = _view(workspace, team)
        status_row = WorkflowStatus.objects.filter(team=team).first()

        for url in (_views_url(team), _board_url(view), _lane_url(view, status_row)):
            response = api_client.get(url)
            assert response.status_code == 401, url

    @pytest.mark.real_feature_flags
    def test_flag_off_returns_403_feature_not_enabled(self, api_client, board):
        """The established flag-gate convention (RequiresFeatureFlag): the
        endpoints EXIST but answer 403 "Feature not enabled." while the flag
        is off — mirroring the timer endpoints in this same controller, and
        the 403 feature_disabled convention across pillar controllers. Never
        a 404."""
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        view = _view(workspace, team)
        status_row = WorkflowStatus.objects.filter(team=team).first()
        FeatureFlag.objects.get_or_create(key=FLAG_KEY, defaults={"default_enabled": False})
        bump_feature_flags_version()

        api_client.force_authenticate(owner)
        for url in (_views_url(team), _board_url(view), _lane_url(view, status_row)):
            response = api_client.get(url)
            assert response.status_code == 403, url
            assert "Feature not enabled" in str(response.data)

    @pytest.mark.real_feature_flags
    def test_flag_off_leaves_the_column_board_untouched(self, api_client, board):
        """P2a is additive: with the flag off nothing about today's board
        read changes."""
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        FeatureFlag.objects.get_or_create(key=FLAG_KEY, defaults={"default_enabled": False})
        bump_feature_flags_version()

        api_client.force_authenticate(owner)
        url = reverse("project:columns-by-team-workspace", kwargs={"team_id": team.id, "workspace_id": workspace.id})
        response = api_client.get(url)
        assert response.status_code == 200
        assert len(response.data["data"]) == len(CANONICAL_STATUSES)

    @pytest.mark.real_feature_flags
    def test_workspace_scoped_enable_rule_opens_the_endpoints(self, api_client, board):
        """Per-workspace opt-in: default OFF + a WORKSPACE enable rule → 200.

        Also proves the flag is evaluated against the RESOURCE's workspace
        (the team's), resolved by the view's ``get_feature_flag_workspace_id``
        hook — not against the requester's active workspace."""
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        view = _view(workspace, team)
        flag, _ = FeatureFlag.objects.get_or_create(key=FLAG_KEY, defaults={"default_enabled": False})
        FeatureFlagRule.objects.create(
            flag=flag, scope=FeatureFlagRule.Scope.WORKSPACE, workspace=workspace, enabled=True
        )
        bump_feature_flags_version()

        api_client.force_authenticate(owner)
        assert api_client.get(_views_url(team)).status_code == 200
        assert api_client.get(_board_url(view)).status_code == 200


# ---------------------------------------------------------------------------
# Views list
# ---------------------------------------------------------------------------


class TestTeamViewsList:
    def test_returns_the_teams_views_ordered_with_fields(self, api_client, board):
        owner, workspace, team = board
        project = Project.objects.create(workspace=workspace, team=team, title="AI Findings", created_by=owner)
        _view(workspace, team, slug="board", name="Board", order=0)
        _view(
            workspace,
            team,
            slug=f"project-{project.id}",
            name="AI Findings",
            filter={"project": str(project.id)},
            order=1,
        )

        api_client.force_authenticate(owner)
        response = api_client.get(_views_url(team))

        assert response.status_code == 200
        data = response.data["data"]
        assert [v["slug"] for v in data] == ["board", f"project-{project.id}"]
        first = data[0]
        for field in ("id", "team", "workspace", "name", "slug", "filter", "group_by", "order", "is_system"):
            assert field in first, field
        assert first["is_system"] is True
        assert first["filter"] == {}
        assert data[1]["filter"] == {"project": str(project.id)}

    def test_workspace_member_outside_the_team_is_403(self, api_client, board, user_factory):
        _owner, workspace, team = board
        _view(workspace, team)
        colleague = user_factory()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=colleague,
            role=WorkspaceMembership.Role.MEMBER,
            status=WorkspaceMembership.Status.ACTIVE,
        )

        api_client.force_authenticate(colleague)
        assert api_client.get(_views_url(team)).status_code == 403

    def test_other_workspace_team_id_is_404_not_403(
        self, api_client, board, workspace_factory, team_factory, user_factory
    ):
        _owner_a, workspace_a, team_a = board
        _view(workspace_a, team_a)
        outsider, _workspace_b, _team_b = _board(workspace_factory, team_factory, user_factory)

        api_client.force_authenticate(outsider)
        response = api_client.get(_views_url(team_a))
        assert response.status_code == 404

    def test_unknown_team_id_is_404(self, api_client, board):
        owner, _workspace, _team = board
        api_client.force_authenticate(owner)
        assert api_client.get(reverse("project:team-board-views", kwargs={"team_id": 999999})).status_code == 404


# ---------------------------------------------------------------------------
# View board — lanes + membership
# ---------------------------------------------------------------------------


class TestViewBoardLanes:
    def test_lanes_are_the_teams_statuses_ordered_with_category(self, api_client, board):
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        response = api_client.get(_board_url(view))

        assert response.status_code == 200
        assert response.data["data"]["view"]["slug"] == "board"
        lanes = response.data["data"]["lanes"]
        assert [lane["name"] for lane in lanes] == [name for name, _c, _o in CANONICAL_STATUSES]
        assert [lane["category"] for lane in lanes] == [category for _n, category, _o in CANONICAL_STATUSES]
        for lane in lanes:
            # `title` mirrors `name` so HudKanbanBoard's lane.title keeps working.
            assert lane["title"] == lane["name"]
            for field in ("id", "order", "tasks", "tasks_total", "tasks_has_more"):
                assert field in lane, field

    def test_tasks_group_by_workflow_status(self, api_client, board):
        owner, workspace, team = board
        columns, _statuses = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="planned")
        _task(workspace, team, owner, columns["In Progress"], title="doing")
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))

        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["planned"]
        assert [t["title"] for t in lanes["In Progress"]["tasks"]] == ["doing"]
        assert lanes["Backlog"]["tasks"] == []

    def test_task_without_a_status_appears_in_no_lane(self, api_client, board):
        # Parity with the column board: a column-less task sits on no board.
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        Task.objects.create(workspace=workspace, team=team, column=None, title="loose", created_by=owner)
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert all(lane["tasks_total"] == 0 for lane in lanes.values())

    def test_archived_tasks_are_excluded(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="live")
        _task(workspace, team, owner, columns["Todo"], title="trashed", status=Task.ARCHIVED)
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert lanes["Todo"]["tasks_total"] == 1
        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["live"]


# ---------------------------------------------------------------------------
# View board — the closed filter vocabulary
# ---------------------------------------------------------------------------


class TestViewBoardFilters:
    def test_project_filter_scopes_membership(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        p1 = Project.objects.create(workspace=workspace, team=team, title="P1", created_by=owner)
        p2 = Project.objects.create(workspace=workspace, team=team, title="P2", created_by=owner)
        _task(workspace, team, owner, columns["Todo"], title="p1 card", project=p1)
        _task(workspace, team, owner, columns["Todo"], title="p2 card", project=p2)
        _task(workspace, team, owner, columns["Todo"], title="teamwide card")
        # The P1 backfill stores project ids as strings — exercise that shape.
        view = _view(workspace, team, slug=f"project-{p1.id}", name="P1", filter={"project": str(p1.id)})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["p1 card"]
        assert lanes["Todo"]["tasks_total"] == 1

    def test_min_severity_filter_is_a_floor_over_metadata_severity(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="low", order=0, metadata={"severity": "low"})
        _task(workspace, team, owner, columns["Todo"], title="high", order=1, metadata={"severity": "high"})
        _task(workspace, team, owner, columns["Todo"], title="critical", order=2, metadata={"severity": "critical"})
        _task(workspace, team, owner, columns["Todo"], title="unrated", order=3)
        view = _view(workspace, team, slug="hot", name="Hot", filter={"min_severity": "high"})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["high", "critical"]

    def test_project_and_min_severity_compose(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        p1 = Project.objects.create(workspace=workspace, team=team, title="P1", created_by=owner)
        _task(workspace, team, owner, columns["Todo"], title="p1 high", project=p1, metadata={"severity": "high"})
        _task(workspace, team, owner, columns["Todo"], title="p1 low", project=p1, metadata={"severity": "low"})
        _task(workspace, team, owner, columns["Todo"], title="stray high", metadata={"severity": "high"})
        view = _view(workspace, team, slug="p1-hot", name="P1 hot", filter={"project": p1.id, "min_severity": "high"})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["p1 high"]

    def test_source_type_filter_matches_exactly(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="posture", source_type="ai.cloud_posture_drift")
        _task(workspace, team, owner, columns["Todo"], title="logwatch", source_type="ai.error_burst")
        _task(workspace, team, owner, columns["Todo"], title="human")
        view = _view(workspace, team, slug="posture", name="Posture", filter={"source_type": "ai.cloud_posture_drift"})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["posture"]

    def test_assignee_filter_matches_assigned_tasks(self, api_client, board, user_factory):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        teammate = user_factory()
        team.members.add(teammate)
        mine = _task(workspace, team, owner, columns["Todo"], title="mine")
        mine.assigned_to.add(teammate)
        _task(workspace, team, owner, columns["Todo"], title="unassigned")
        view = _view(workspace, team, slug="mine", name="Mine", filter={"assignee": str(teammate.id)})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["mine"]

    def test_tag_filter_fails_closed_until_task_tagging_exists(self, api_client, board):
        """Task-level tags land with ADR 0015's later phase; until then a
        tag-filtered view matches NOTHING (a filter that cannot apply must
        narrow, never silently widen)."""
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="anything")
        view = _view(workspace, team, slug="tagged", name="Tagged", filter={"tag": "env:prod"})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert all(lane["tasks_total"] == 0 for lane in lanes.values())

    def test_malformed_filter_values_fail_closed(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="card", metadata={"severity": "high"})

        api_client.force_authenticate(owner)
        for bad_filter in ({"min_severity": "apocalyptic"}, {"project": "not-a-pk"}, {"assignee": "not-a-uuid"}):
            view = _view(workspace, team, slug=f"bad-{next(iter(bad_filter))}", name="Bad", filter=bad_filter)
            lanes = _lanes_by_name(api_client.get(_board_url(view)))
            assert all(lane["tasks_total"] == 0 for lane in lanes.values()), bad_filter


# ---------------------------------------------------------------------------
# The P3 system-view filter keys (ADR 0030 Decision §3: Intake / Acting)
# ---------------------------------------------------------------------------


class TestP3SystemViewFilters:
    def test_source_type_prefix_matches_every_ai_source(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="posture", source_type="ai.cloud_posture")
        _task(workspace, team, owner, columns["Todo"], title="logwatch", source_type="ai.log_watch")
        _task(workspace, team, owner, columns["Todo"], title="human")
        view = _view(workspace, team, slug="ai", name="AI", filter={"source_type_prefix": "ai."})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert sorted(t["title"] for t in lanes["Todo"]["tasks"]) == ["logwatch", "posture"]

    def test_category_view_renders_only_its_categorys_lanes(self, api_client, board):
        """The Intake view is an honest funnel surface: only the unstarted
        lanes render, and only AI-sourced unstarted cards populate them."""
        owner, workspace, team = board
        columns, _statuses = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="fresh finding", source_type="ai.log_watch")
        _task(workspace, team, owner, columns["In Progress"], title="acting finding", source_type="ai.log_watch")
        _task(workspace, team, owner, columns["Todo"], title="human todo")
        intake = _view(
            workspace,
            team,
            slug="intake",
            name="Intake",
            filter={"source_type_prefix": "ai.", "category": "unstarted"},
        )

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(intake)))
        assert set(lanes) == {"Todo"}  # unstarted = the Todo lane only
        assert [t["title"] for t in lanes["Todo"]["tasks"]] == ["fresh finding"]

    def test_acting_view_shows_started_ai_cards(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["In Progress"], title="acting", source_type="ai.log_watch")
        _task(workspace, team, owner, columns["Testing"], title="verifying", source_type="ai.code_security")
        _task(workspace, team, owner, columns["Todo"], title="fresh", source_type="ai.log_watch")
        acting = _view(
            workspace,
            team,
            slug="acting",
            name="Acting",
            filter={"source_type_prefix": "ai.", "category": "started"},
        )

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(acting)))
        assert set(lanes) == {"In Progress", "Testing"}  # both started lanes
        assert [t["title"] for t in lanes["In Progress"]["tasks"]] == ["acting"]
        assert [t["title"] for t in lanes["Testing"]["tasks"]] == ["verifying"]

    def test_unknown_category_fails_closed(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="card", source_type="ai.log_watch")
        view = _view(workspace, team, slug="bad-cat", name="Bad")
        # Bypass model validation the way drift/tampering would.
        BoardView.objects.filter(pk=view.pk).update(filter={"category": "sideways"})

        api_client.force_authenticate(owner)
        response = api_client.get(_board_url(view))
        assert response.data["data"]["lanes"] == []

    def test_bad_source_type_prefix_fails_closed(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        _task(workspace, team, owner, columns["Todo"], title="card", source_type="ai.log_watch")
        view = _view(workspace, team, slug="bad-prefix", name="Bad prefix")
        BoardView.objects.filter(pk=view.pk).update(filter={"source_type_prefix": ""})

        api_client.force_authenticate(owner)
        lanes = _lanes_by_name(api_client.get(_board_url(view)))
        assert all(lane["tasks_total"] == 0 for lane in lanes.values())


# ---------------------------------------------------------------------------
# Windowing parity with the column board
# ---------------------------------------------------------------------------


class TestViewBoardWindowing:
    def test_lane_is_windowed_with_total_and_has_more(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        for i in range(7):
            _task(workspace, team, owner, columns["Todo"], title=f"Task {i}", order=i)
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        response = api_client.get(_board_url(view), {"tasks_limit": 5})

        lane = _lanes_by_name(response)["Todo"]
        assert len(lane["tasks"]) == 5
        assert lane["tasks_total"] == 7
        assert lane["tasks_has_more"] is True
        # Board order parity: ('order', 'created_at') — the window is the head.
        assert [t["title"] for t in lane["tasks"]] == [f"Task {i}" for i in range(5)]

    def test_default_window_matches_the_column_board(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        for i in range(DEFAULT_COLUMN_TASKS_LIMIT + 2):
            _task(workspace, team, owner, columns["Todo"], title=f"Task {i}", order=i)
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        lane = _lanes_by_name(api_client.get(_board_url(view)))["Todo"]
        assert len(lane["tasks"]) == DEFAULT_COLUMN_TASKS_LIMIT
        assert lane["tasks_total"] == DEFAULT_COLUMN_TASKS_LIMIT + 2
        assert lane["tasks_has_more"] is True

    def test_tasks_limit_is_clamped_like_the_column_board(self, api_client, board):
        owner, workspace, team = board
        columns, _ = _seed_lanes(workspace, team, owner)
        for i in range(3):
            _task(workspace, team, owner, columns["Todo"], title=f"Task {i}", order=i)
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        for raw in ("999999", "0", "-5", "junk"):
            lane = _lanes_by_name(api_client.get(_board_url(view), {"tasks_limit": raw}))["Todo"]
            assert len(lane["tasks"]) <= MAX_COLUMN_TASKS_LIMIT
            assert lane["tasks_total"] == 3


class TestViewLaneTasksLoadMore:
    def test_pages_are_contiguous_without_skips_or_dupes(self, api_client, board):
        owner, workspace, team = board
        columns, statuses = _seed_lanes(workspace, team, owner)
        for i in range(9):
            _task(workspace, team, owner, columns["Todo"], title=f"Task {i}", order=i)
        view = _view(workspace, team)

        api_client.force_authenticate(owner)
        url = _lane_url(view, statuses["Todo"])
        seen, offset = [], 0
        while True:
            response = api_client.get(url, {"offset": offset, "limit": 4})
            assert response.status_code == 200
            meta = response.data["meta"]
            page_titles = [t["title"] for t in response.data["data"]]
            seen.extend(page_titles)
            assert meta["total"] == 9
            if not meta["has_more"]:
                break
            offset += len(page_titles)

        assert seen == [f"Task {i}" for i in range(9)]

    def test_pager_applies_the_view_filter(self, api_client, board):
        owner, workspace, team = board
        columns, statuses = _seed_lanes(workspace, team, owner)
        p1 = Project.objects.create(workspace=workspace, team=team, title="P1", created_by=owner)
        for i in range(3):
            _task(workspace, team, owner, columns["Todo"], title=f"p1 {i}", order=i, project=p1)
        _task(workspace, team, owner, columns["Todo"], title="stray", order=9)
        view = _view(workspace, team, slug=f"project-{p1.id}", name="P1", filter={"project": str(p1.id)})

        api_client.force_authenticate(owner)
        response = api_client.get(_lane_url(view, statuses["Todo"]), {"limit": 10})
        assert response.data["meta"]["total"] == 3
        assert [t["title"] for t in response.data["data"]] == [f"p1 {i}" for i in range(3)]


# ---------------------------------------------------------------------------
# Isolation (tenancy invariant 8)
# ---------------------------------------------------------------------------


class TestIsolation:
    def test_other_workspace_view_id_is_404_not_403(
        self, api_client, board, workspace_factory, team_factory, user_factory
    ):
        owner_a, workspace_a, team_a = board
        _seed_lanes(workspace_a, team_a, owner_a)
        view_a = _view(workspace_a, team_a)
        statuses_a = {s.name: s for s in WorkflowStatus.objects.filter(team=team_a)}
        outsider, _workspace_b, _team_b = _board(workspace_factory, team_factory, user_factory)

        api_client.force_authenticate(outsider)
        assert api_client.get(_board_url(view_a)).status_code == 404
        assert api_client.get(_lane_url(view_a, statuses_a["Todo"])).status_code == 404

    def test_view_board_never_contains_another_workspaces_tasks(
        self, api_client, board, workspace_factory, team_factory, user_factory
    ):
        owner_a, workspace_a, team_a = board
        columns_a, _ = _seed_lanes(workspace_a, team_a, owner_a)
        _task(workspace_a, team_a, owner_a, columns_a["Todo"], title="a card")

        owner_b, workspace_b, team_b = _board(workspace_factory, team_factory, user_factory)
        columns_b, _ = _seed_lanes(workspace_b, team_b, owner_b)
        _task(workspace_b, team_b, owner_b, columns_b["Todo"], title="b secret")

        view_a = _view(workspace_a, team_a)
        api_client.force_authenticate(owner_a)
        response = api_client.get(_board_url(view_a))

        titles = [t["title"] for lane in response.data["data"]["lanes"] for t in lane["tasks"]]
        assert titles == ["a card"]

    def test_lane_pager_rejects_another_teams_status_id(
        self, api_client, board, workspace_factory, team_factory, user_factory
    ):
        """A valid view id + another workspace's status id must 404 — the
        pager can never be used to read a foreign team's lane."""
        owner_a, workspace_a, team_a = board
        _seed_lanes(workspace_a, team_a, owner_a)
        view_a = _view(workspace_a, team_a)

        owner_b, workspace_b, team_b = _board(workspace_factory, team_factory, user_factory)
        _seed_lanes(workspace_b, team_b, owner_b)
        status_b = WorkflowStatus.objects.filter(team=team_b, name="Todo").get()

        api_client.force_authenticate(owner_a)
        assert api_client.get(_lane_url(view_a, status_b)).status_code == 404

    def test_views_list_only_returns_the_requested_teams_views(
        self, api_client, board, workspace_factory, team_factory, user_factory
    ):
        owner_a, workspace_a, team_a = board
        _view(workspace_a, team_a, slug="board", name="A board")
        _owner_b, workspace_b, team_b = _board(workspace_factory, team_factory, user_factory)
        _view(workspace_b, team_b, slug="board", name="B board")

        api_client.force_authenticate(owner_a)
        response = api_client.get(_views_url(team_a))
        assert [v["name"] for v in response.data["data"]] == ["A board"]
