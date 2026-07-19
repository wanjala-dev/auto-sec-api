"""End-to-end tests for the workspace feed endpoints.

Covers the follow-filter semantics that are the whole point of this
feature: members only see posts from people they follow, owners bypass
the filter, auto-follow kicks in on private-workspace join.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

from infrastructure.persistence.users.models import UserProfile
from infrastructure.persistence.workspaces.models import Workspace, WorkspaceMembership


def _make_profile(user):
    """UserProfile is created lazily — ensure one exists for follow writes."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def _follow(follower, followee):
    profile = _make_profile(followee)
    profile.followers.add(follower)


def _add_member(workspace, user, *, role=WorkspaceMembership.Role.MEMBER):
    return WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=role,
        status=WorkspaceMembership.Status.ACTIVE,
    )


@pytest.mark.django_db
class TestWorkspaceFeedEndpoints:
    def _post_via_api(self, api_client, user, workspace, body, team_id=None):
        api_client.force_authenticate(user=user)
        url = reverse("workspace-feed", kwargs={"workspace_id": workspace.id})
        payload = {"body": body}
        if team_id is not None:
            payload["team_id"] = team_id
        return api_client.post(url, payload, format="json")

    def _list_via_api(self, api_client, viewer, workspace, team_id=None):
        api_client.force_authenticate(user=viewer)
        url = reverse("workspace-feed", kwargs={"workspace_id": workspace.id})
        qs = {}
        if team_id is not None:
            qs["team_id"] = team_id
        return api_client.get(url, qs)

    def test_non_member_cannot_list_feed(self, api_client, user_factory, workspace_factory):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        stranger = user_factory()
        response = self._list_via_api(api_client, stranger, ws)
        assert response.status_code == 403

    def test_non_member_cannot_post(self, api_client, user_factory, workspace_factory):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        stranger = user_factory()
        response = self._post_via_api(api_client, stranger, ws, "hi")
        assert response.status_code == 403

    def test_member_sees_only_followed_members_posts(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        alice = user_factory()
        bob = user_factory()
        charlie = user_factory()
        for u in (alice, bob, charlie):
            _add_member(ws, u)

        # Alice follows Bob but not Charlie.
        _follow(alice, bob)

        assert self._post_via_api(api_client, bob, ws, "bob says hi").status_code == 201
        assert self._post_via_api(api_client, charlie, ws, "charlie says hi").status_code == 201
        assert self._post_via_api(api_client, alice, ws, "alice says hi").status_code == 201

        response = self._list_via_api(api_client, alice, ws)
        assert response.status_code == 200
        bodies = {p["body"] for p in response.data["data"]["posts"]}
        assert bodies == {"bob says hi", "alice says hi"}

    def test_owner_bypasses_follow_filter(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        alice = user_factory()
        bob = user_factory()
        _add_member(ws, alice)
        _add_member(ws, bob)

        # Owner follows nobody.
        assert self._post_via_api(api_client, alice, ws, "hey").status_code == 201
        assert self._post_via_api(api_client, bob, ws, "yo").status_code == 201

        response = self._list_via_api(api_client, owner, ws)
        bodies = {p["body"] for p in response.data["data"]["posts"]}
        assert bodies == {"hey", "yo"}

    def test_viewer_always_sees_their_own_posts(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        alice = user_factory()
        _add_member(ws, alice)

        assert self._post_via_api(api_client, alice, ws, "my post").status_code == 201
        response = self._list_via_api(api_client, alice, ws)
        bodies = [p["body"] for p in response.data["data"]["posts"]]
        assert bodies == ["my post"]

    def test_edit_and_delete_own_post(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        alice = user_factory()
        _add_member(ws, alice)
        resp = self._post_via_api(api_client, alice, ws, "original")
        post_id = resp.data["data"]["id"]

        api_client.force_authenticate(user=alice)
        edit_url = reverse("workspace-feed-post-detail", kwargs={"post_id": post_id})
        edit_resp = api_client.patch(edit_url, {"body": "edited"}, format="json")
        assert edit_resp.status_code == 200
        assert edit_resp.data["data"]["body"] == "edited"
        assert edit_resp.data["data"]["edited_on"] is not None

        del_resp = api_client.delete(edit_url)
        assert del_resp.status_code == 204
        # Feed now excludes the deleted post.
        response = self._list_via_api(api_client, alice, ws)
        assert response.data["data"]["posts"] == []

    def test_non_author_cannot_edit_or_delete(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        alice = user_factory()
        bob = user_factory()
        for u in (alice, bob):
            _add_member(ws, u)

        resp = self._post_via_api(api_client, alice, ws, "hey")
        post_id = resp.data["data"]["id"]

        api_client.force_authenticate(user=bob)
        edit_url = reverse("workspace-feed-post-detail", kwargs={"post_id": post_id})
        assert api_client.patch(edit_url, {"body": "x"}, format="json").status_code == 403
        assert api_client.delete(edit_url).status_code == 403

    def test_owner_can_delete_any_post(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        ws = workspace_factory(owner=owner)
        alice = user_factory()
        _add_member(ws, alice)
        resp = self._post_via_api(api_client, alice, ws, "hey")
        post_id = resp.data["data"]["id"]

        api_client.force_authenticate(user=owner)
        url = reverse("workspace-feed-post-detail", kwargs={"post_id": post_id})
        assert api_client.delete(url).status_code == 204


@pytest.mark.django_db
class TestAutoFollowOnPrivateWorkspaceJoin:
    def test_auto_follow_triggers_on_personal_workspace(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        _make_profile(owner)
        ws = workspace_factory(owner=owner, workspace_type=Workspace.PERSONAL)
        existing = user_factory()
        _make_profile(existing)
        _add_member(ws, existing)

        # Pre-existing state: owner and existing are already in the workspace but
        # haven't followed one another. Now a new member joins.
        newcomer = user_factory()
        _make_profile(newcomer)
        _add_member(ws, newcomer)

        # Newcomer's feed is not empty because we auto-followed everybody.
        api_client.force_authenticate(user=owner)
        url = reverse("workspace-feed", kwargs={"workspace_id": ws.id})
        api_client.post(url, {"body": "welcome"}, format="json")

        api_client.force_authenticate(user=newcomer)
        response = api_client.get(url)
        bodies = [p["body"] for p in response.data["data"]["posts"]]
        assert bodies == ["welcome"]

    def test_teamspace_does_not_auto_follow(
        self, api_client, user_factory, workspace_factory
    ):
        owner = user_factory()
        _make_profile(owner)
        ws = workspace_factory(owner=owner, workspace_type=Workspace.TEAMSPACE)
        newcomer = user_factory()
        _make_profile(newcomer)
        _add_member(ws, newcomer)

        # Owner posts; newcomer does NOT follow them, so the feed is empty.
        api_client.force_authenticate(user=owner)
        url = reverse("workspace-feed", kwargs={"workspace_id": ws.id})
        api_client.post(url, {"body": "hi team"}, format="json")

        api_client.force_authenticate(user=newcomer)
        response = api_client.get(url)
        assert response.data["data"]["posts"] == []
