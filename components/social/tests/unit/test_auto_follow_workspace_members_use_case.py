"""Unit tests for AutoFollowWorkspaceMembersUseCase."""

from __future__ import annotations

from uuid import uuid4

from components.social.application.ports.follow_writer_port import FollowWriterPort
from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)
from components.social.application.use_cases.auto_follow_workspace_members_use_case import (
    AutoFollowWorkspaceMembersUseCase,
)


class _FakeFollowWriter(FollowWriterPort):
    def __init__(self):
        self.edges: list[tuple] = []

    def add_follow(self, *, follower_id, followee_id):
        self.edges.append((follower_id, followee_id))


class _FakeMembership(WorkspaceMembershipReaderPort):
    def __init__(self, members):
        self._members = frozenset(members)

    def list_workspace_member_ids(self, workspace_id):
        return self._members

    def is_workspace_owner(self, **kwargs):
        return False

    def list_user_team_ids(self, **kwargs):
        return frozenset()

    def is_team_member(self, **kwargs):
        return False


class TestAutoFollowWorkspaceMembersUseCase:
    def test_creates_mutual_follow_with_every_existing_member(self):
        new_member = uuid4()
        a, b, c = uuid4(), uuid4(), uuid4()
        ws = uuid4()
        writer = _FakeFollowWriter()
        use_case = AutoFollowWorkspaceMembersUseCase(
            follow_writer=writer,
            memberships=_FakeMembership({new_member, a, b, c}),
        )
        edges = use_case.execute(new_member_id=new_member, workspace_id=ws)
        assert edges == 6  # 3 existing members × 2 directions
        incoming = {f for f, t in writer.edges if t == new_member}
        outgoing = {t for f, t in writer.edges if f == new_member}
        assert incoming == {a, b, c}
        assert outgoing == {a, b, c}

    def test_solo_member_noop(self):
        solo = uuid4()
        ws = uuid4()
        writer = _FakeFollowWriter()
        use_case = AutoFollowWorkspaceMembersUseCase(
            follow_writer=writer,
            memberships=_FakeMembership({solo}),
        )
        assert use_case.execute(new_member_id=solo, workspace_id=ws) == 0
        assert writer.edges == []
