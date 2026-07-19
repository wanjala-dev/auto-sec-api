"""Unit tests for ListWorkspaceFeedUseCase with fake ports."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from components.social.application.ports.follow_reader_port import FollowReaderPort
from components.social.application.ports.post_store_port import (
    FeedPage,
    PostStorePort,
)
from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)
from components.social.application.queries.list_workspace_feed_query import (
    ListWorkspaceFeedQuery,
)
from components.social.application.use_cases.list_workspace_feed_use_case import (
    FeedAuthorizationError,
    ListWorkspaceFeedUseCase,
)
from components.social.domain.entities.post_entity import PostEntity, PostVisibility


class _FakePostStore(PostStorePort):
    def __init__(self):
        self.last_call = None

    def save(self, post):
        raise NotImplementedError

    def find_by_id(self, post_id):
        raise NotImplementedError

    def update_body(self, *, post_id, body, edited_on):
        raise NotImplementedError

    def soft_delete(self, *, post_id):
        raise NotImplementedError

    def list_workspace_feed(
        self, *, viewer_id, workspace_id, followed_user_ids, team_id=None, cursor=None, limit=20
    ):
        self.last_call = dict(
            viewer_id=viewer_id,
            workspace_id=workspace_id,
            followed_user_ids=frozenset(followed_user_ids),
            team_id=team_id,
            cursor=cursor,
            limit=limit,
        )
        return FeedPage(posts=[], next_cursor=None)


class _FakeFollowReader(FollowReaderPort):
    def __init__(self, follows=None):
        self._follows = frozenset(follows or set())

    def list_followed_user_ids(self, user_id):
        return self._follows

    def is_following(self, *, user_id, target_id):
        return target_id in self._follows


class _FakeMembership(WorkspaceMembershipReaderPort):
    def __init__(self, members=None, is_owner=False, user_teams=None, team_members=None):
        self._members = frozenset(members or set())
        self._is_owner = is_owner
        self._user_teams = frozenset(user_teams or set())
        self._team_members = team_members or {}

    def list_workspace_member_ids(self, workspace_id):
        return self._members

    def is_workspace_owner(self, *, user_id, workspace_id):
        return self._is_owner

    def list_user_team_ids(self, *, user_id, workspace_id):
        return self._user_teams

    def is_team_member(self, *, user_id, team_id):
        return user_id in self._team_members.get(team_id, set())


class TestListWorkspaceFeedUseCase:
    def test_non_member_is_rejected(self):
        viewer = uuid4()
        ws = uuid4()
        use_case = ListWorkspaceFeedUseCase(
            post_store=_FakePostStore(),
            follows=_FakeFollowReader(),
            memberships=_FakeMembership(members=set(), is_owner=False),
        )
        with pytest.raises(FeedAuthorizationError):
            use_case.execute(ListWorkspaceFeedQuery(viewer_id=viewer, workspace_id=ws))

    def test_member_sees_follow_filtered_feed(self):
        viewer = uuid4()
        followed = uuid4()
        stranger = uuid4()
        ws = uuid4()
        store = _FakePostStore()
        use_case = ListWorkspaceFeedUseCase(
            post_store=store,
            follows=_FakeFollowReader(follows={followed}),
            memberships=_FakeMembership(members={viewer, followed, stranger}),
        )
        use_case.execute(ListWorkspaceFeedQuery(viewer_id=viewer, workspace_id=ws))
        assert store.last_call["followed_user_ids"] == frozenset({followed, viewer})

    def test_owner_sees_everything_no_follow_filter(self):
        viewer = uuid4()
        a, b, c = uuid4(), uuid4(), uuid4()
        ws = uuid4()
        store = _FakePostStore()
        use_case = ListWorkspaceFeedUseCase(
            post_store=store,
            follows=_FakeFollowReader(follows=set()),
            memberships=_FakeMembership(members={a, b, c}, is_owner=True),
        )
        use_case.execute(ListWorkspaceFeedQuery(viewer_id=viewer, workspace_id=ws))
        # Owner path: followed set equals all members (no filter in practice).
        assert store.last_call["followed_user_ids"] == frozenset({a, b, c})

    def test_non_team_member_is_rejected_for_team_feed(self):
        viewer = uuid4()
        ws = uuid4()
        use_case = ListWorkspaceFeedUseCase(
            post_store=_FakePostStore(),
            follows=_FakeFollowReader(),
            memberships=_FakeMembership(members={viewer}, user_teams=set()),
        )
        with pytest.raises(FeedAuthorizationError):
            use_case.execute(
                ListWorkspaceFeedQuery(viewer_id=viewer, workspace_id=ws, team_id=7)
            )

    def test_team_member_sees_team_feed(self):
        viewer = uuid4()
        ws = uuid4()
        store = _FakePostStore()
        use_case = ListWorkspaceFeedUseCase(
            post_store=store,
            follows=_FakeFollowReader(),
            memberships=_FakeMembership(
                members={viewer},
                user_teams={7},
                team_members={7: {viewer}},
            ),
        )
        use_case.execute(
            ListWorkspaceFeedQuery(viewer_id=viewer, workspace_id=ws, team_id=7)
        )
        assert store.last_call["team_id"] == 7
