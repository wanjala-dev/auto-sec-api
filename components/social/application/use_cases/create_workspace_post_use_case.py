"""Create a post on a workspace or team feed."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from components.social.application.commands.create_workspace_post_command import (
    CreateWorkspacePostCommand,
)
from components.social.application.ports.post_store_port import (
    CreatePostInput,
    PostStorePort,
)
from components.social.application.ports.workspace_membership_reader_port import (
    WorkspaceMembershipReaderPort,
)
from components.social.domain.entities.post_entity import PostEntity, PostVisibility
from components.social.domain.errors import PostAuthorizationError

logger = logging.getLogger(__name__)


@dataclass
class CreateWorkspacePostUseCase:
    post_store: PostStorePort
    memberships: WorkspaceMembershipReaderPort

    def execute(self, command: CreateWorkspacePostCommand) -> PostEntity:
        member_ids = self.memberships.list_workspace_member_ids(command.workspace_id)
        is_owner = self.memberships.is_workspace_owner(
            user_id=command.author_id, workspace_id=command.workspace_id
        )
        if command.author_id not in member_ids and not is_owner:
            raise PostAuthorizationError(
                "Author is not a member of the workspace."
            )

        if command.visibility == PostVisibility.TEAM:
            if command.team_id is None:
                raise PostAuthorizationError("Team-scoped posts require a team_id.")
            if not is_owner and not self.memberships.is_team_member(
                user_id=command.author_id, team_id=command.team_id
            ):
                raise PostAuthorizationError("Author is not a member of the team.")

        post = self.post_store.save(
            CreatePostInput(
                author_id=command.author_id,
                workspace_id=command.workspace_id,
                team_id=command.team_id,
                visibility=command.visibility,
                body=command.body,
                image_ids=command.image_ids,
            )
        )
        logger.info(
            "workspace_post_created post_id=%s author_id=%s workspace_id=%s team_id=%s visibility=%s",
            post.id,
            command.author_id,
            command.workspace_id,
            command.team_id,
            command.visibility.value,
        )
        return post
