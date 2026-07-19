"""Soft-delete a feed post.

Only the author or a workspace owner can delete. The row stays in the DB
so replies aren't orphaned; the feed query filters out ``is_deleted`` rows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from components.social.application.ports.post_store_port import PostStorePort
from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)
from components.social.domain.errors import (
    PostAuthorizationError,
    PostNotFoundError,
)

logger = logging.getLogger(__name__)


@dataclass
class DeletePostUseCase:
    post_store: PostStorePort
    memberships: WorkspaceMembershipReaderPort

    def execute(self, *, post_id: int, actor_id: UUID) -> None:
        post = self.post_store.find_by_id(post_id)
        if post is None or post.is_deleted:
            raise PostNotFoundError(f"Post {post_id} not found.")

        is_author = post.author_id == actor_id
        is_owner = (
            post.workspace_id is not None
            and self.memberships.is_workspace_owner(
                user_id=actor_id, workspace_id=post.workspace_id
            )
        )
        if not (is_author or is_owner):
            raise PostAuthorizationError("Only the author or workspace owner can delete this post.")

        self.post_store.soft_delete(post_id=post_id)
        logger.info(
            "workspace_post_deleted post_id=%s actor_id=%s is_owner=%s",
            post_id,
            actor_id,
            is_owner,
        )
