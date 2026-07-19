"""Unit tests for CreateWorkspacePostUseCase."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from components.social.application.commands.create_workspace_post_command import (
    CreateWorkspacePostCommand,
)
from components.social.application.ports.post_store_port import PostStorePort
from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)
from components.social.application.use_cases.create_workspace_post_use_case import (
    CreateWorkspacePostUseCase,
    PostAuthorizationError,
)
from components.social.domain.entities.post_entity import PostEntity, PostVisibility


class _FakeStore(PostStorePort):
    def __init__(self):
        self.saved = None

    def save(self, post):
        self.saved = post
        return PostEntity(
            id=42,
            author_id=post.author_id,
            workspace_id=post.workspace_id,
            team_id=post.team_id,
            visibility=post.visibility,
            body=post.body,
            image_ids=tuple(post.image_ids),
            created_on=datetime.now(timezone.utc),
        )

    def find_by_id(self, post_id):
        raise NotImplementedError

    def update_body(self, *, post_id, body, edited_on):
        raise NotImplementedError

    def soft_delete(self, *, post_id):
        raise NotImplementedError

    def list_workspace_feed(self, **kwargs):
        raise NotImplementedError


class _FakeMembership(WorkspaceMembershipReaderPort):
    def __init__(self, members=None, is_owner=False, team_members=None):
        self._members = frozenset(members or set())
        self._is_owner = is_owner
        self._team_members = team_members or {}

    def list_workspace_member_ids(self, workspace_id):
        return self._members

    def is_workspace_owner(self, *, user_id, workspace_id):
        return self._is_owner

    def list_user_team_ids(self, *, user_id, workspace_id):
        raise NotImplementedError

    def is_team_member(self, *, user_id, team_id):
        return user_id in self._team_members.get(team_id, set())


class TestCreateWorkspacePostUseCase:
    def test_non_member_cannot_post(self):
        author, ws = uuid4(), uuid4()
        use_case = CreateWorkspacePostUseCase(
            post_store=_FakeStore(),
            memberships=_FakeMembership(members=set()),
        )
        cmd = CreateWorkspacePostCommand.build(
            author_id=author, workspace_id=ws, body="hi"
        )
        with pytest.raises(PostAuthorizationError):
            use_case.execute(cmd)

    def test_member_can_post_to_workspace(self):
        author, ws = uuid4(), uuid4()
        store = _FakeStore()
        use_case = CreateWorkspacePostUseCase(
            post_store=store,
            memberships=_FakeMembership(members={author}),
        )
        cmd = CreateWorkspacePostCommand.build(
            author_id=author, workspace_id=ws, body="hi"
        )
        post = use_case.execute(cmd)
        assert post.id == 42
        assert post.visibility == PostVisibility.WORKSPACE
        assert store.saved.body == "hi"

    def test_non_team_member_cannot_post_to_team_feed(self):
        author, ws = uuid4(), uuid4()
        use_case = CreateWorkspacePostUseCase(
            post_store=_FakeStore(),
            memberships=_FakeMembership(members={author}, team_members={5: set()}),
        )
        cmd = CreateWorkspacePostCommand.build(
            author_id=author, workspace_id=ws, body="hi", team_id=5
        )
        with pytest.raises(PostAuthorizationError):
            use_case.execute(cmd)

    def test_team_member_can_post_to_team_feed(self):
        author, ws = uuid4(), uuid4()
        use_case = CreateWorkspacePostUseCase(
            post_store=_FakeStore(),
            memberships=_FakeMembership(members={author}, team_members={5: {author}}),
        )
        cmd = CreateWorkspacePostCommand.build(
            author_id=author, workspace_id=ws, body="hi", team_id=5
        )
        post = use_case.execute(cmd)
        assert post.visibility == PostVisibility.TEAM
        assert post.team_id == 5

    def test_owner_can_post_to_any_team(self):
        author, ws = uuid4(), uuid4()
        use_case = CreateWorkspacePostUseCase(
            post_store=_FakeStore(),
            memberships=_FakeMembership(
                members=set(), is_owner=True, team_members={5: set()}
            ),
        )
        cmd = CreateWorkspacePostCommand.build(
            author_id=author, workspace_id=ws, body="hi", team_id=5
        )
        post = use_case.execute(cmd)
        assert post.team_id == 5
