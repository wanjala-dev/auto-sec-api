"""Edit the body of a feed post.

Only the author can edit. ``edited_on`` is stamped so the UI can surface
"edited" without tracking a full history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from components.social.application.ports.post_store_port import PostStorePort
from components.social.domain.entities.post_entity import PostEntity
from components.social.domain.errors import (
    PostAuthorizationError,
    PostNotFoundError,
    PostValidationError,
)

logger = logging.getLogger(__name__)


@dataclass
class EditPostUseCase:
    post_store: PostStorePort

    def execute(self, *, post_id: int, actor_id: UUID, body: str) -> PostEntity:
        post = self.post_store.find_by_id(post_id)
        if post is None or post.is_deleted:
            raise PostNotFoundError(f"Post {post_id} not found.")
        if post.author_id != actor_id:
            raise PostAuthorizationError("Only the author can edit this post.")
        if not body or not body.strip():
            raise PostValidationError("Post body cannot be empty.")
        updated = self.post_store.update_body(
            post_id=post_id, body=body, edited_on=datetime.now(timezone.utc)
        )
        logger.info("workspace_post_edited post_id=%s actor_id=%s", post_id, actor_id)
        return updated
