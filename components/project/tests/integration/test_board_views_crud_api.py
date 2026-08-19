"""Integration — persisted saved views CRUD (task #74, on ADR 0030's substrate).

Contract under test:

* ``POST /project/teams/<team_id>/views/`` — save a personal view: closed
  filter vocabulary (validated by the model — one enforcement point),
  ``is_system=False`` and ``created_by=request.user`` ALWAYS (mass-assignment
  protection), slug minted from the name and de-duplicated, order appended
  after the team's existing views.
* ``PATCH /project/views/<view_id>/`` — rename / re-filter / reorder OWN
  views (creator, or workspace admin/owner via the established admin bypass);
  partial; slug stable across renames.
* ``DELETE /project/views/<view_id>/`` — same authorization contract.
* System views are IMMUTABLE — 403 with an explicit message, never edited.
* Visibility: a personal view exists for its creator only — every other
  member gets the SAME 404 a missing id gets, on list, board read, lane
  pager, PATCH and DELETE alike (admins/owners bypass for management, but
  the list stays personal for everyone).
* Flag gating: same ``feature.boards_as_views`` / ``RequiresFeatureFlag``
  convention as the P2a reads (flag off → 403 "Feature not enabled.").
* Isolation (tenancy invariant 8): cross-workspace ids answer 404, never
  403, and nothing ever leaks across the tenant boundary.
"""

from __future__ import annotations

import pytest
from django.urls import reverse

from components.project.tests.integration.test_board_views_api import (
    _board,
    _board_url,
    _seed_lanes,
    _view,
    _views_url,
)
from components.shared_platform.infrastructure.services.feature_flags import (
    bump_feature_flags_version,
)
from infrastructure.persistence.core.models import FeatureFlag
from infrastructure.persistence.project.models import BoardView
from infrastructure.persistence.workspaces.models import WorkspaceMembership

pytestmark = pytest.mark.django_db

FLAG_KEY = "feature.boards_as_views"


def _detail_url(view):
    return reverse("project:view-detail", kwargs={"view_id": view.id})


def _detail_url_for_id(view_id):
    return reverse("project:view-detail", kwargs={"view_id": view_id})


def _post_view(api_client, team, **body):
    return api_client.post(_views_url(team), body, format="json")


def _add_member(workspace, team, user, *, role=WorkspaceMembership.Role.MEMBER):
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        status=WorkspaceMembership.Status.ACTIVE,
    )
    team.members.add(user)
    return user


@pytest.fixture
def board(workspace_factory, team_factory, user_factory):
    return _board(workspace_factory, team_factory, user_factory)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreateView:
    def test_member_saves_a_personal_view(self, api_client, board):
        owner, workspace, team = board
        _view(workspace, team)  # the system board, order 0

        api_client.force_authenticate(owner)
        response = _post_view(api_client, team, name="High severity", filter={"min_severity": "high"})

        assert response.status_code == 201, response.data
        data = response.data["data"]
        assert data["name"] == "High severity"
        assert data["slug"] == "high-severity"
        assert data["filter"] == {"min_severity": "high"}
        assert data["group_by"] == "status"
        assert data["is_system"] is False
        assert data["mine"] is True
        assert str(data["created_by"]) == str(owner.id)

        row = BoardView.objects.get(pk=data["id"])
        assert row.created_by_id == owner.id
        assert row.is_system is False
        assert row.workspace_id == workspace.id
        assert row.team_id == team.id

    def test_saved_view_is_appended_after_existing_views(self, api_client, board):
        owner, workspace, team = board
        _view(workspace, team, slug="board", name="Board", order=0)
        _view(workspace, team, slug="hot", name="Hot", order=5)

        api_client.force_authenticate(owner)
        response = _post_view(api_client, team, name="Mine")

        assert response.status_code == 201
        assert response.data["data"]["order"] == 6

        listed = api_client.get(_views_url(team))
        assert [v["slug"] for v in listed.data["data"]] == ["board", "hot", "mine"]
        assert [v["mine"] for v in listed.data["data"]] == [False, False, True]

    def test_name_is_required(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        for body in ({}, {"name": ""}, {"name": "   "}, {"name": 42}):
            response = _post_view(api_client, team, **body)
            assert response.status_code == 400, body
            assert "name" in str(response.data).lower()

    def test_unknown_filter_keys_are_rejected_through_the_model_check(self, api_client, board):
        """The closed vocabulary (ADR 0030) is the MODEL's invariant; the API
        must surface its rejection as a 400, not bypass or restate it."""
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        response = _post_view(api_client, team, name="Sneaky", filter={"jql": "project = X"})
        assert response.status_code == 400
        assert "jql" in str(response.data)
        # Nothing was persisted. Scoped to non-system rows: the team's own
        # derived system view ("board") is minted at team-create by
        # ``django_system_board_view_bridge`` and is not this POST's doing.
        assert not BoardView.objects.filter(team=team, is_system=False).exists()
        assert not BoardView.objects.filter(team=team, name="Sneaky").exists()

    def test_non_dict_filter_is_rejected(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        response = _post_view(api_client, team, name="Bad", filter="min_severity=high")
        assert response.status_code == 400

    def test_unsupported_group_by_is_rejected(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        response = _post_view(api_client, team, name="Grouped", group_by="assignee")
        assert response.status_code == 400
        assert "group_by" in str(response.data)

    def test_slug_deduplicates_against_existing_slugs(self, api_client, board):
        owner, workspace, team = board
        _view(workspace, team, slug="board", name="Board")  # system slug taken

        api_client.force_authenticate(owner)
        first = _post_view(api_client, team, name="Board")
        second = _post_view(api_client, team, name="Board")

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.data["data"]["slug"] == "board-2"
        assert second.data["data"]["slug"] == "board-3"

    def test_body_cannot_choose_owner_system_flag_or_tenancy_fields(
        self, api_client, board, workspace_factory, team_factory, user_factory
    ):
        """Mass-assignment: created_by comes from auth, is_system is always
        False, and team/workspace come from the URL-resolved team — a body
        naming any of them (or a foreign workspace) changes nothing."""
        owner, workspace, team = board
        other_owner, other_workspace, other_team = _board(workspace_factory, team_factory, user_factory)

        api_client.force_authenticate(owner)
        response = api_client.post(
            _views_url(team),
            {
                "name": "Sneaky",
                "is_system": True,
                "created_by": str(other_owner.id),
                "workspace": str(other_workspace.id),
                "team": other_team.id,
                "slug": "hacked",
                "order": 0,
            },
            format="json",
        )

        assert response.status_code == 201
        row = BoardView.objects.get(pk=response.data["data"]["id"])
        assert row.is_system is False
        assert row.created_by_id == owner.id
        assert row.workspace_id == workspace.id
        assert row.team_id == team.id
        assert row.slug == "sneaky"
        assert row.order == 1  # appended, not the body's 0

    def test_workspace_member_outside_the_team_is_403(self, api_client, board, user_factory):
        _owner, workspace, team = board
        colleague = user_factory()
        WorkspaceMembership.objects.create(
            workspace=workspace,
            user=colleague,
            role=WorkspaceMembership.Role.MEMBER,
            status=WorkspaceMembership.Status.ACTIVE,
        )

        api_client.force_authenticate(colleague)
        assert _post_view(api_client, team, name="Nope").status_code == 403

    def test_viewer_role_team_member_can_save_a_personal_view(self, api_client, board, user_factory):
        """Saving a view is a read-side personalization — it creates a row
        only its creator sees and mutates nothing shared. So it follows the
        BOARD-READ authorization (team membership), not the mutation gates:
        viewers who can see the board can save their own lens on it."""
        _owner, workspace, team = board
        viewer = _add_member(workspace, team, user_factory(), role=WorkspaceMembership.Role.VIEWER)

        api_client.force_authenticate(viewer)
        response = _post_view(api_client, team, name="My lens")
        assert response.status_code == 201
        assert response.data["data"]["mine"] is True

    def test_other_workspace_team_id_is_404(self, api_client, board, workspace_factory, team_factory, user_factory):
        _owner_a, _workspace_a, team_a = board
        outsider, _workspace_b, _team_b = _board(workspace_factory, team_factory, user_factory)

        api_client.force_authenticate(outsider)
        assert _post_view(api_client, team_a, name="Probe").status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class TestUpdateView:
    def _saved_view(self, api_client, team, **body):
        response = _post_view(api_client, team, **{"name": "Mine", **body})
        assert response.status_code == 201
        return BoardView.objects.get(pk=response.data["data"]["id"])

    def test_creator_renames_refilters_and_reorders(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team, filter={"min_severity": "low"})

        response = api_client.patch(
            _detail_url(view),
            {"name": "Critical only", "filter": {"min_severity": "critical"}, "order": 9},
            format="json",
        )

        assert response.status_code == 200, response.data
        data = response.data["data"]
        assert data["name"] == "Critical only"
        assert data["filter"] == {"min_severity": "critical"}
        assert data["order"] == 9
        assert data["slug"] == "mine"  # slug is stable identity — renames keep it
        view.refresh_from_db()
        assert view.name == "Critical only"
        assert view.order == 9

    def test_partial_update_leaves_other_fields_untouched(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team, filter={"min_severity": "high"})

        response = api_client.patch(_detail_url(view), {"name": "Renamed"}, format="json")

        assert response.status_code == 200
        view.refresh_from_db()
        assert view.name == "Renamed"
        assert view.filter == {"min_severity": "high"}

    def test_patch_rejects_unknown_filter_keys(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team)

        response = api_client.patch(_detail_url(view), {"filter": {"jql": "x"}}, format="json")
        assert response.status_code == 400
        view.refresh_from_db()
        assert view.filter == {}

    def test_patch_rejects_blank_name_and_bad_order(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team)

        assert api_client.patch(_detail_url(view), {"name": "  "}, format="json").status_code == 400
        assert api_client.patch(_detail_url(view), {"order": "junk"}, format="json").status_code == 400

    def test_patch_cannot_flip_ownership_or_system_flag(self, api_client, board, user_factory):
        owner, workspace, team = board
        teammate = _add_member(workspace, team, user_factory())
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team)

        response = api_client.patch(
            _detail_url(view),
            {"is_system": True, "created_by": str(teammate.id), "slug": "hacked", "name": "Still mine"},
            format="json",
        )

        assert response.status_code == 200
        view.refresh_from_db()
        assert view.is_system is False
        assert view.created_by_id == owner.id
        assert view.slug == "mine"

    def test_system_view_is_immutable_403_with_a_clear_message(self, api_client, board):
        owner, workspace, team = board
        system_view = _view(workspace, team)

        api_client.force_authenticate(owner)
        response = api_client.patch(_detail_url(system_view), {"name": "Renamed"}, format="json")

        assert response.status_code == 403
        assert "immutable" in str(response.data["message"]).lower()
        system_view.refresh_from_db()
        assert system_view.name == "Board"

    def test_another_members_patch_is_404_like_a_missing_id(self, api_client, board, user_factory):
        owner, workspace, team = board
        teammate = _add_member(workspace, team, user_factory())
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team)

        api_client.force_authenticate(teammate)
        response = api_client.patch(_detail_url(view), {"name": "Taken over"}, format="json")

        assert response.status_code == 404
        view.refresh_from_db()
        assert view.name == "Mine"

    def test_workspace_admin_may_manage_a_members_view(self, api_client, board, user_factory):
        owner, workspace, team = board
        member = _add_member(workspace, team, user_factory())
        admin = _add_member(workspace, team, user_factory(), role=WorkspaceMembership.Role.ADMIN)

        api_client.force_authenticate(member)
        view = self._saved_view(api_client, team)

        api_client.force_authenticate(admin)
        response = api_client.patch(_detail_url(view), {"name": "Tidied by admin"}, format="json")

        assert response.status_code == 200
        view.refresh_from_db()
        assert view.name == "Tidied by admin"
        assert view.created_by_id == member.id  # management never reassigns ownership

    def test_other_workspace_view_id_is_404_not_403(
        self, api_client, board, workspace_factory, team_factory, user_factory
    ):
        owner_a, _workspace_a, team_a = board
        api_client.force_authenticate(owner_a)
        view = self._saved_view(api_client, team_a)

        outsider, _workspace_b, _team_b = _board(workspace_factory, team_factory, user_factory)
        api_client.force_authenticate(outsider)
        assert api_client.patch(_detail_url(view), {"name": "x"}, format="json").status_code == 404

    def test_unknown_view_id_is_404(self, api_client, board):
        owner, _workspace, _team = board
        api_client.force_authenticate(owner)
        assert api_client.patch(_detail_url_for_id(999999), {"name": "x"}, format="json").status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDeleteView:
    def _saved_view(self, api_client, team):
        response = _post_view(api_client, team, name="Mine")
        assert response.status_code == 201
        return BoardView.objects.get(pk=response.data["data"]["id"])

    def test_creator_deletes_own_view(self, api_client, board):
        owner, _workspace, team = board
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team)

        response = api_client.delete(_detail_url(view))

        assert response.status_code == 204
        assert not BoardView.objects.filter(pk=view.pk).exists()

    def test_system_view_delete_is_403_and_survives(self, api_client, board):
        owner, workspace, team = board
        system_view = _view(workspace, team)

        api_client.force_authenticate(owner)
        response = api_client.delete(_detail_url(system_view))

        assert response.status_code == 403
        assert "immutable" in str(response.data["message"]).lower()
        assert BoardView.objects.filter(pk=system_view.pk).exists()

    def test_another_members_delete_is_404_and_view_survives(self, api_client, board, user_factory):
        owner, workspace, team = board
        teammate = _add_member(workspace, team, user_factory())
        api_client.force_authenticate(owner)
        view = self._saved_view(api_client, team)

        api_client.force_authenticate(teammate)
        assert api_client.delete(_detail_url(view)).status_code == 404
        assert BoardView.objects.filter(pk=view.pk).exists()

    def test_workspace_admin_may_delete_a_members_view(self, api_client, board, user_factory):
        owner, workspace, team = board
        member = _add_member(workspace, team, user_factory())
        admin = _add_member(workspace, team, user_factory(), role=WorkspaceMembership.Role.ADMIN)

        api_client.force_authenticate(member)
        view = self._saved_view(api_client, team)

        api_client.force_authenticate(admin)
        assert api_client.delete(_detail_url(view)).status_code == 204
        assert not BoardView.objects.filter(pk=view.pk).exists()

    def test_other_workspace_delete_is_404(self, api_client, board, workspace_factory, team_factory, user_factory):
        owner_a, _workspace_a, team_a = board
        api_client.force_authenticate(owner_a)
        view = self._saved_view(api_client, team_a)

        outsider, _workspace_b, _team_b = _board(workspace_factory, team_factory, user_factory)
        api_client.force_authenticate(outsider)
        assert api_client.delete(_detail_url(view)).status_code == 404
        assert BoardView.objects.filter(pk=view.pk).exists()


# ---------------------------------------------------------------------------
# Per-user visibility (Tom's ask: saved views are PERSONAL)
# ---------------------------------------------------------------------------


class TestPersonalVisibility:
    def test_list_shows_system_views_plus_only_my_views(self, api_client, board, user_factory):
        owner, workspace, team = board
        teammate = _add_member(workspace, team, user_factory())
        _view(workspace, team)  # shared system board

        api_client.force_authenticate(owner)
        assert _post_view(api_client, team, name="Owners lens").status_code == 201
        api_client.force_authenticate(teammate)
        assert _post_view(api_client, team, name="Teammates lens").status_code == 201

        teammate_names = [v["name"] for v in api_client.get(_views_url(team)).data["data"]]
        api_client.force_authenticate(owner)
        owner_names = [v["name"] for v in api_client.get(_views_url(team)).data["data"]]

        assert owner_names == ["Board", "Owners lens"]
        assert teammate_names == ["Board", "Teammates lens"]

    def test_user_views_list_after_system_views_regardless_of_order_values(self, api_client, board):
        """`-is_system` leads the ordering: even a personal view whose order
        undercuts a system view's renders after the system block."""
        owner, workspace, team = board
        _view(workspace, team, slug="board", name="Board", order=5)

        api_client.force_authenticate(owner)
        created = _post_view(api_client, team, name="Mine")
        BoardView.objects.filter(pk=created.data["data"]["id"]).update(order=0)

        names = [v["name"] for v in api_client.get(_views_url(team)).data["data"]]
        assert names == ["Board", "Mine"]

    def test_admins_list_stays_personal_too(self, api_client, board, user_factory):
        """Admins can MANAGE any personal view by id (cleanup) but the bar is
        personal for everyone — a member's saved lenses are not surfaced to
        admins in the list."""
        owner, workspace, team = board
        admin = _add_member(workspace, team, user_factory(), role=WorkspaceMembership.Role.ADMIN)
        _view(workspace, team)

        api_client.force_authenticate(owner)
        assert _post_view(api_client, team, name="Owners lens").status_code == 201

        api_client.force_authenticate(admin)
        names = [v["name"] for v in api_client.get(_views_url(team)).data["data"]]
        assert names == ["Board"]

    def test_board_read_of_another_members_personal_view_is_404(self, api_client, board, user_factory):
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        teammate = _add_member(workspace, team, user_factory())

        api_client.force_authenticate(owner)
        created = _post_view(api_client, team, name="Owners lens")
        view = BoardView.objects.get(pk=created.data["data"]["id"])

        assert api_client.get(_board_url(view)).status_code == 200  # creator reads it
        api_client.force_authenticate(teammate)
        assert api_client.get(_board_url(view)).status_code == 404  # teammate never sees it

    def test_system_views_stay_readable_by_every_team_member(self, api_client, board, user_factory):
        owner, workspace, team = board
        _seed_lanes(workspace, team, owner)
        teammate = _add_member(workspace, team, user_factory())
        system_view = _view(workspace, team)

        api_client.force_authenticate(teammate)
        assert api_client.get(_board_url(system_view)).status_code == 200


# ---------------------------------------------------------------------------
# Flag gating (the established RequiresFeatureFlag convention)
# ---------------------------------------------------------------------------


class TestFlagGate:
    @pytest.mark.real_feature_flags
    def test_flag_off_returns_403_feature_not_enabled_for_writes(self, api_client, board):
        owner, workspace, team = board
        view = _view(workspace, team, is_system=False)
        BoardView.objects.filter(pk=view.pk).update(created_by=owner)
        FeatureFlag.objects.get_or_create(key=FLAG_KEY, defaults={"default_enabled": False})
        bump_feature_flags_version()

        api_client.force_authenticate(owner)
        post = _post_view(api_client, team, name="Nope")
        patch = api_client.patch(_detail_url(view), {"name": "Nope"}, format="json")
        delete = api_client.delete(_detail_url(view))

        for response in (post, patch, delete):
            assert response.status_code == 403
            assert "Feature not enabled" in str(response.data)
        assert BoardView.objects.filter(pk=view.pk, name="Board").exists()

    def test_unauthenticated_writes_are_401(self, api_client, board):
        owner, workspace, team = board
        view = _view(workspace, team)

        assert api_client.post(_views_url(team), {"name": "x"}, format="json").status_code == 401
        assert api_client.patch(_detail_url(view), {"name": "x"}, format="json").status_code == 401
        assert api_client.delete(_detail_url(view)).status_code == 401
