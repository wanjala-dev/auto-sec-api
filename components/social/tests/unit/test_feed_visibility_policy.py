"""Unit tests for feed visibility policy."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from components.social.domain.entities.post_entity import PostEntity, PostVisibility
from components.social.domain.policies.feed_visibility_policy import (
    ViewerContext,
    is_post_visible,
)


def _make_post(author_id, workspace_id, team_id=None, visibility=PostVisibility.WORKSPACE, is_deleted=False):
    return PostEntity(
        id=1,
        author_id=author_id,
        workspace_id=workspace_id,
        team_id=team_id,
        visibility=visibility,
        body="hi",
        created_on=datetime.now(timezone.utc),
        is_deleted=is_deleted,
    )


def _viewer(viewer_id, *, follows=(), members=(), teams=(), is_owner=False):
    return ViewerContext(
        viewer_id=viewer_id,
        followed_user_ids=frozenset(follows),
        workspace_member_ids=frozenset(members),
        viewer_team_ids=frozenset(teams),
        is_workspace_owner=is_owner,
    )


class TestFeedVisibilityPolicy:
    def test_author_sees_own_post(self):
        author = uuid4()
        ws = uuid4()
        post = _make_post(author, ws)
        viewer = _viewer(author, members={author})
        assert is_post_visible(post, viewer) is True

    def test_deleted_post_hidden_even_from_author(self):
        author = uuid4()
        post = _make_post(author, uuid4(), is_deleted=True)
        viewer = _viewer(author, members={author})
        assert is_post_visible(post, viewer) is False

    def test_workspace_post_visible_to_follower(self):
        author, viewer_id, ws = uuid4(), uuid4(), uuid4()
        post = _make_post(author, ws)
        viewer = _viewer(viewer_id, follows={author}, members={author, viewer_id})
        assert is_post_visible(post, viewer) is True

    def test_workspace_post_hidden_from_non_follower(self):
        author, viewer_id, ws = uuid4(), uuid4(), uuid4()
        post = _make_post(author, ws)
        viewer = _viewer(viewer_id, follows=set(), members={author, viewer_id})
        assert is_post_visible(post, viewer) is False

    def test_workspace_post_hidden_from_non_member_even_if_followed(self):
        author, viewer_id, ws = uuid4(), uuid4(), uuid4()
        post = _make_post(author, ws)
        viewer = _viewer(viewer_id, follows={author}, members={viewer_id})
        assert is_post_visible(post, viewer) is False

    def test_owner_sees_all_workspace_posts(self):
        author, viewer_id, ws = uuid4(), uuid4(), uuid4()
        post = _make_post(author, ws)
        viewer = _viewer(viewer_id, follows=set(), members={author}, is_owner=True)
        assert is_post_visible(post, viewer) is True

    def test_team_post_requires_team_membership(self):
        author, viewer_id, ws = uuid4(), uuid4(), uuid4()
        post = _make_post(author, ws, team_id=5, visibility=PostVisibility.TEAM)
        viewer_outside = _viewer(viewer_id, follows={author}, members={author, viewer_id})
        assert is_post_visible(post, viewer_outside) is False
        viewer_inside = _viewer(
            viewer_id, follows={author}, members={author, viewer_id}, teams={5}
        )
        assert is_post_visible(post, viewer_inside) is True

    def test_public_post_visible_to_stranger(self):
        author, viewer_id = uuid4(), uuid4()
        post = _make_post(author, workspace_id=None, visibility=PostVisibility.PUBLIC)
        viewer = _viewer(viewer_id)
        assert is_post_visible(post, viewer) is True
