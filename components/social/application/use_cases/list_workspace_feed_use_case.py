"""List a workspace or team feed for a viewer.

The viewer only sees posts authored by workspace members they follow, plus
their own posts. Workspace owners bypass the follow filter.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from components.social.application.ports.follow_reader_port import FollowReaderPort
from components.social.application.ports.post_store_port import FeedPage, PostStorePort
from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)
from components.social.application.queries.list_workspace_feed_query import (
    ListWorkspaceFeedQuery,
)
from components.social.domain.errors import FeedAuthorizationError

logger = logging.getLogger(__name__)


@dataclass
class ListWorkspaceFeedUseCase:
    post_store: PostStorePort
    follows: FollowReaderPort
    memberships: WorkspaceMembershipReaderPort

    def execute(self, query: ListWorkspaceFeedQuery) -> FeedPage:
        is_owner = self.memberships.is_workspace_owner(
            user_id=query.viewer_id, workspace_id=query.workspace_id
        )
        member_ids = self.memberships.list_workspace_member_ids(query.workspace_id)
        if not is_owner and query.viewer_id not in member_ids:
            raise FeedAuthorizationError("Viewer is not a member of this workspace.")

        if query.team_id is not None and not is_owner:
            if not self.memberships.is_team_member(
                user_id=query.viewer_id, team_id=query.team_id
            ):
                raise FeedAuthorizationError("Viewer is not a member of this team.")

        if is_owner:
            # Owners see everything in their workspace — no follow filter.
            followed_ids = frozenset(member_ids)
        else:
            followed_ids = self.follows.list_followed_user_ids(query.viewer_id)
            # Always include the viewer's own posts.
            followed_ids = frozenset(followed_ids | {query.viewer_id})

        page = self.post_store.list_workspace_feed(
            viewer_id=query.viewer_id,
            workspace_id=query.workspace_id,
            followed_user_ids=followed_ids,
            team_id=query.team_id,
            cursor=query.cursor,
            limit=query.limit,
        )
        logger.info(
            "workspace_feed_listed viewer_id=%s workspace_id=%s team_id=%s count=%d",
            query.viewer_id,
            query.workspace_id,
            query.team_id,
            len(page.posts),
        )
        return page
