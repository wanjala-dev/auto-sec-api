"""Auto-follow the rest of a private workspace when a user joins.

Fixes the "empty feed" UX: when someone joins a Private workspace, we wire
up mutual follows with every existing member so the feed has signal on day
one. Called by the workspace-membership signal bridge in infrastructure.

Teamspaces are NOT auto-followed — see ``.claude/rules`` discussion on
the default visibility tradeoff. For teamspaces, the frontend shows a
"suggested members" rail on empty feeds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from components.social.application.ports.follow_writer_port import FollowWriterPort
from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)

logger = logging.getLogger(__name__)


@dataclass
class AutoFollowWorkspaceMembersUseCase:
    follow_writer: FollowWriterPort
    memberships: WorkspaceMembershipReaderPort

    def execute(self, *, new_member_id: UUID, workspace_id: UUID) -> int:
        member_ids = self.memberships.list_workspace_member_ids(workspace_id)
        others = {uid for uid in member_ids if uid != new_member_id}
        edges_added = 0
        for other_id in others:
            # Mutual follow: new member sees existing members' posts AND the
            # new member's posts surface in existing members' feeds.
            self.follow_writer.add_follow(
                follower_id=new_member_id, followee_id=other_id
            )
            self.follow_writer.add_follow(
                follower_id=other_id, followee_id=new_member_id
            )
            edges_added += 2
        logger.info(
            "auto_follow_workspace_members applied new_member_id=%s workspace_id=%s edges=%d",
            new_member_id,
            workspace_id,
            edges_added,
        )
        return edges_added
